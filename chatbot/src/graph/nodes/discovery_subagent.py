"""
Discovery SubAgent 노드.

담당 TaskIntent:
  - SEARCH_SIMILAR_TEXT  : 텍스트 기반 상품 검색 및 스타일 추천
    - SEARCH_SIMILAR_IMAGE : 이미지 URL 기반 유사 상품 검색 (CLIP/Qdrant 경로)

파이프라인 (다이어그램 기준):
    TEXT  경로: CLIP/Qdrant Retrieve (search_by_text_clip / recommend_clothes)
    IMAGE 경로: CLIP/Qdrant → (실패 시) VLM → CLIP/Qdrant Retrieve (search_by_text_clip)

설계 원칙:
  - current_active_task 로 TEXT / IMAGE 경로를 분기.
    - IMAGE 경로: CLIP/Qdrant 기반 이미지 유사 검색을 우선 수행.
        실패 시 OpenAI Vision 기반 텍스트 검색으로 fallback.
    - TEXT  경로: ReAct 에이전트로 search_by_text_clip / recommend_clothes 도구 선택.
  - 검색 결과는 search_context 에 저장하여 Final Generator 가 활용.
"""

import re
import base64
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from chatbot.src.graph.brand_profiles import resolve_brand_profile
from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.infrastructure.site_retrieval import use_runtime_site_id
from chatbot.src.schemas.planner import TaskIntent
from chatbot.src.graph.llm_providers import make_chat_llm
from chatbot.src.tools.recommendation_tools import (
    recommend_clothes,
    search_by_image,
    search_by_text_clip,
)
from chatbot.src.infrastructure.openai import get_openai_client
from chatbot.src.runtime.uploads import UPLOAD_ROOT as CHATBOT_UPLOAD_DIR


CURRENT_FILE = Path(__file__).resolve()
REPO_ROOT = CURRENT_FILE.parents[4]

DISCOVERY_SYSTEM_PROMPT = """당신은 {brand_store_label}의 Discovery SubAgent입니다.
사용자가 원하는 상품을 찾아주는 역할을 합니다.

[도구 선택 기준]
- `search_by_text_clip`    : 텍스트 기반 스타일/무드/유사 이미지 검색.
  예) "겨울 패딩", "흰색 린넨 셔츠", "나이키 운동화"
- `recommend_clothes`      : 카테고리/용도/계절 조합의 스타일 추천.
  예) "여름에 입을 캐주얼 상의", "파티용 드레스"
  단, 카테고리(상의/하의/원피스 등)가 불명확하면 도구를 호출하지 말고 먼저 질문하세요.

[중요]
- 사용자가 상품명/색상/카테고리를 이미 말했으면 되묻지 말고 먼저 `search_by_text_clip`을 호출하세요.
- 한국어 질의도 바로 검색 도구를 호출해도 됩니다.

[User Context]
{user_context}
"""

NON_ECOMMERCE_DISCOVERY_SYSTEM_PROMPT = """당신은 {brand_store_label}의 Discovery SubAgent입니다.
사용자가 원하는 상품을 찾아주는 역할을 합니다.

[도구 선택 기준]
- `search_by_text_clip` : 텍스트 기반 상품 검색과 유사 상품 추천.
  예) "수분크림 추천", "흰색 린넨 셔츠", "짜장면 비슷한 메뉴"

[중요]
- 사용자가 상품명/색상/카테고리를 이미 말했으면 되묻지 말고 먼저 `search_by_text_clip`을 호출하세요.
- 카테고리/가격/브랜드 조건이 포함되면 그대로 검색어에 반영하세요.

[User Context]
{user_context}
"""

VLM_DESCRIBE_PROMPT = """이 이미지에 있는 패션 아이템을 상세히 설명해주세요.
다음 항목을 포함하여 설명하세요:
- 의류 종류 (예: 반팔티, 청바지, 원피스 등)
- 색상
- 소재나 질감 (보이는 경우)
- 스타일 특징 (예: 오버핏, 슬림핏, 캐주얼, 포멀 등)

검색 쿼리에 바로 사용할 수 있도록 간결하게 작성하세요."""


def _extract_top_k_from_text(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    return max(1, min(20, int(match.group(1))))


def _load_image_bytes(image_url: str) -> bytes:
    raw_path = Path(image_url).expanduser()
    if raw_path.exists():
        return raw_path.read_bytes()

    repo_relative_path = (REPO_ROOT / image_url).resolve()
    if repo_relative_path.exists():
        return repo_relative_path.read_bytes()

    parsed = urlparse(image_url)
    if parsed.path.startswith("/uploads/chatbot/"):
        filename = parsed.path.rsplit("/", 1)[-1]
        local_path = CHATBOT_UPLOAD_DIR / filename
        if local_path.exists():
            return local_path.read_bytes()

    with urlopen(image_url, timeout=10) as response:
        return response.read()


def _bytes_to_data_url(image_bytes: bytes, image_url: str) -> str:
    parsed = urlparse(image_url)
    path = parsed.path.lower()
    mime_type = "image/jpeg"
    if path.endswith(".png"):
        mime_type = "image/png"
    elif path.endswith(".webp"):
        mime_type = "image/webp"
    elif path.endswith(".gif"):
        mime_type = "image/gif"
    elif path.endswith(".bmp"):
        mime_type = "image/bmp"
    elif path.endswith(".avif"):
        mime_type = "image/avif"

    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


# ── 노드 함수 ─────────────────────────────────────────────

def discovery_subagent_node(state: GlobalAgentState) -> dict:
    """
    Discovery SubAgent.
    current_active_task 에 따라 TEXT / IMAGE 경로로 분기합니다.
    """
    task = state.get("current_active_task")
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")

    if task == TaskIntent.SEARCH_SIMILAR_IMAGE:
        return _image_search_pipeline(state, provider, model, task)
    else:
        return _text_search_pipeline(state, provider, model, task)


def run_discovery_pipeline(
    user_query: str,
    image_url: str | None = None,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    user_info: dict | None = None,
) -> dict:
    """평가/배치 실행용 Discovery 파이프라인 래퍼."""
    task = (
        TaskIntent.SEARCH_SIMILAR_IMAGE
        if image_url
        else TaskIntent.SEARCH_SIMILAR_TEXT
    )

    message_content = (user_query or "").strip()
    if image_url:
        if message_content:
            message_content = f"{message_content}\n[image_url]: {image_url}"
        else:
            message_content = f"[image_url]: {image_url}"

    state: GlobalAgentState = {
        "messages": [HumanMessage(content=message_content)],
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": task,
        "order_context": {},
        "search_context": {
            "search_query": (user_query or "").strip(),
            **({"image_url": image_url} if image_url else {}),
        },
        "ui_action_required": None,
        "user_info": user_info or {"id": 1, "name": "평가 사용자"},
        "llm_provider": provider,
        "llm_model": model,
        "agent_results": {},
        "guardrail_passed": True,
        "conversation_id": "discovery-eval",
        "turn_id": "discovery-eval-turn",
        "conversation_summary": None,
    }

    result = discovery_subagent_node(state)
    search_context = {**state.get("search_context", {}), **result.get("search_context", {})}
    messages = result.get("messages", [])
    agent_results = result.get("agent_results", {})
    answer_content = _get_last_ai_content(messages) or str(agent_results.get(task, "") or "")

    return {
        "task": task,
        "messages": messages,
        "search_context": search_context,
        "retrieved_products": list(search_context.get("retrieved_products", [])),
        "ui_action_required": result.get("ui_action_required"),
        "answer_content": answer_content,
        "agent_results": agent_results,
    }


# ── TEXT 경로 ──────────────────────────────────────────────

def _text_search_pipeline(
    state: GlobalAgentState, provider: str, model: str, task: str | None
) -> dict:
    """텍스트 기반 상품 검색: ReAct 에이전트로 도구 선택."""
    latest_query = _extract_latest_user_query(state.get("messages", []))
    site_id = (state.get("user_info") or {}).get("site_id")
    with use_runtime_site_id(site_id):
        direct_result = _run_direct_text_search(latest_query)
    if direct_result is not None:
        retrieved_products = direct_result.get("products", [])
        answer_text = _build_direct_search_answer(latest_query, retrieved_products)
        answer_message = AIMessage(content=answer_text)
        return {
            "messages": [answer_message],
            "search_context": {
                **state.get("search_context", {}),
                "search_query": latest_query,
                "retrieved_products": retrieved_products,
            },
            "ui_action_required": "show_product_list" if retrieved_products else None,
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {
                **state.get("agent_results", {}),
                task: answer_text,
            },
        }

    user_info = state.get("user_info", {})
    brand_profile = resolve_brand_profile(user_info.get("site_id"))
    user_context = (
        f"User ID: {user_info.get('id', 'unknown')}, "
        f"Name: {user_info.get('name', '고객')}, "
        f"Brand: {brand_profile.display_name}"
    )

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    agent = create_react_agent(
        model=llm,
        tools=_resolve_discovery_tools(site_id),
        prompt=SystemMessage(
            content=_build_discovery_system_prompt(
                site_id,
                brand_store_label=brand_profile.store_label,
                user_context=user_context,
            )
        ),
    )

    with use_runtime_site_id(site_id):
        result = agent.invoke({"messages": state["messages"]})
    result_messages = result.get("messages", [])

    # 검색 결과 추출 → search_context 업데이트
    search_context = _extract_search_results(result_messages)
    retrieved_products = search_context.get("retrieved_products", [])

    # 마지막 AIMessage 내용을 agent_results 에 저장
    last_ai_content = _get_last_ai_content(result_messages)

    return {
        "messages": result_messages,
        "search_context": {**state.get("search_context", {}), **search_context},
        "ui_action_required": "show_product_list" if retrieved_products else None,
        "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
        "agent_results": {
            **state.get("agent_results", {}),
            task: last_ai_content,
        },
    }


# ── IMAGE 경로 (VLM/CLIP) ──────────────────────────────────

def _image_search_pipeline(
    state: GlobalAgentState, provider: str, model: str, task: str | None
) -> dict:
    """
    이미지 기반 상품 검색.
    Step 1. VLM (OpenAI Vision) — 이미지 → 텍스트 설명
    Step 2. Retrieve            — 설명 텍스트로 벡터 검색
    """
    # search_context 또는 메시지에서 이미지 URL 추출
    image_url = (
        state.get("search_context", {}).get("image_url")
        or _extract_image_url_from_messages(state["messages"])
    )

    if not image_url:
        content = "이미지 URL을 찾을 수 없습니다. 이미지 URL을 함께 보내주세요."
        return {
            "messages": [AIMessage(content=content)],
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {**state.get("agent_results", {}), task: content},
        }

    site_id = (state.get("user_info") or {}).get("site_id")
    query_text = str(state.get("search_context", {}).get("search_query") or "").strip()
    if not query_text:
        query_text = _extract_latest_user_query(state.get("messages", []))

    if not query_text:
        content = "이미지는 확인했어요. 유사/반대/특정 스타일 중 어떤 방식으로 찾아드릴까요?"
        return {
            "messages": [AIMessage(content=content)],
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {**state.get("agent_results", {}), task: content},
            "search_context": {
                **state.get("search_context", {}),
                "image_url": image_url,
            },
        }

    top_k = _extract_top_k_from_text(query_text)
    search_mode = _detect_image_search_mode(query_text)

    image_bytes: bytes | None = None

    # ── Step 1. CLIP/Qdrant 유사 이미지 검색 ───────────────
    try:
        image_bytes = _load_image_bytes(str(image_url))
        search_args = {
            "image_bytes": image_bytes,
            "query_text": query_text,
            "search_mode": search_mode,
        }
        if top_k is not None:
            search_args["top_k"] = top_k
        with use_runtime_site_id(site_id):
            image_result = search_by_image.invoke(search_args)

        if isinstance(image_result, dict) and image_result.get("error"):
            raise RuntimeError(str(image_result["error"]))

        products = image_result.get("products", []) if isinstance(image_result, dict) else []
        ui_action = "show_product_list"
        if search_mode == "opposite":
            answer_text = f"이미지와 반대되는 느낌의 상품 {len(products)}개를 찾았습니다."
        else:
            answer_text = f"이미지와 유사한 상품 {len(products)}개를 찾았습니다."

        return {
            "messages": [AIMessage(content=answer_text)],
            "search_context": {
                **state.get("search_context", {}),
                "image_url": image_url,
                "search_query": query_text,
                "retrieved_products": products,
            },
            "ui_action_required": ui_action,
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {
                **state.get("agent_results", {}),
                task: answer_text,
            },
        }
    except Exception:
        # CLIP/Qdrant 실패 시 VLM 텍스트 검색으로 fallback
        pass

    # ── Step 2. VLM: 이미지 → 텍스트 설명 ──────────────────
    try:
        if image_bytes is None:
            image_bytes = _load_image_bytes(str(image_url))
        openai_image_url = _bytes_to_data_url(image_bytes, str(image_url))

        openai_client = get_openai_client()
        vlm_response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VLM_DESCRIBE_PROMPT},
                        {"type": "image_url", "image_url": {"url": openai_image_url}},
                    ],
                }
            ],
            max_tokens=300,
        )
        image_description = (vlm_response.choices[0].message.content or "").strip()
    except Exception as e:
        content = f"이미지 검색 중 오류가 발생했습니다: {str(e)}"
        return {
            "messages": [AIMessage(content=content)],
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {**state.get("agent_results", {}), task: content},
        }

    # ── Step 2. Retrieve: 설명 텍스트로 벡터 검색 ──────────
    requested_top_k = top_k if top_k is not None else 5
    with use_runtime_site_id(site_id):
        retrieval_result = search_by_text_clip.invoke({
            "query": image_description,
            "top_k": requested_top_k,
            "search_mode": "similar",
        })

    retrieved_products = retrieval_result.get("products", []) if isinstance(retrieval_result, dict) else []
    found_count = len(retrieved_products)

    answer = AIMessage(
        content=(
            f"이미지를 분석했습니다.\n"
            f"**분석 결과**: {image_description}\n\n"
            f"비슷한 스타일의 상품 {found_count}개를 찾았습니다."
        )
    )

    return {
        "messages": [answer],
        "search_context": {
            **state.get("search_context", {}),
            "image_url": image_url,
            "image_description": image_description,
            "retrieved_products": retrieved_products,
        },
        "ui_action_required": "show_product_list" if retrieved_products else None,
        "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
        "agent_results": {
            **state.get("agent_results", {}),
            task: answer.content,
        },
    }


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _get_last_ai_content(messages: list) -> str:
    """마지막 AIMessage 의 텍스트 내용 반환"""
    from langchain_core.messages import AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""


def _extract_image_url_from_messages(messages: list) -> str | None:
    """메시지에서 http(s):// 이미지 URL 추출"""
    import re
    url_pattern = re.compile(r'https?://\S+\.(?:jpg|jpeg|png|webp|gif)', re.IGNORECASE)
    for msg in reversed(messages):
        content = str(getattr(msg, "content", ""))
        match = url_pattern.search(content)
        if match:
            return match.group(0)
    return None


def _extract_search_results(messages: list) -> dict:
    """도구 실행 결과에서 검색된 상품 목록 추출"""
    import json
    from langchain_core.messages import ToolMessage

    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                if isinstance(data, dict):
                    if data.get("products"):
                        return {"retrieved_products": data["products"]}
                    if data.get("ui_data"):
                        return {"retrieved_products": data["ui_data"]}
            except Exception:
                continue
    return {}


def _extract_latest_user_query(messages: list) -> str:
    from langchain_core.messages import HumanMessage

    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        content = str(getattr(msg, "content", "")).strip()
        if not content:
            continue
        # 이벤트 메시지로 들어온 image_url 라인 제거
        cleaned = re.sub(r"\n?\[image_url\]:\s*\S+", "", content).strip()
        if cleaned and "이미지 업로드 완료" not in cleaned:
            return cleaned
    return ""


def _detect_image_search_mode(query: str) -> str:
    lowered = (query or "").lower()
    opposite_keywords = ["반대", "정반대", "다른 느낌", "안 비슷", "opposite", "inverse"]
    for keyword in opposite_keywords:
        if keyword in lowered:
            return "opposite"
    return "similar"


def _resolve_discovery_tools(site_id: str | None) -> list:
    if str(site_id or "").strip() == "site-c":
        return [search_by_text_clip, recommend_clothes]
    return [search_by_text_clip]


def _build_discovery_system_prompt(
    site_id: str | None,
    *,
    brand_store_label: str,
    user_context: str,
) -> str:
    template = (
        DISCOVERY_SYSTEM_PROMPT
        if str(site_id or "").strip() == "site-c"
        else NON_ECOMMERCE_DISCOVERY_SYSTEM_PROMPT
    )
    return template.format(
        brand_store_label=brand_store_label,
        user_context=user_context,
    )


def _should_direct_text_search(query: str) -> bool:
    if not query:
        return False

    direct_keywords = [
        "추천", "찾아", "보여", "백팩", "가방", "신발", "운동화", "스포츠화",
        "셔츠", "티셔츠", "원피스", "드레스", "자켓", "조끼", "청바지", "바지",
        "쿠르타", "쿠르티", "모자", "비니",
    ]
    return any(keyword in query for keyword in direct_keywords)


def _run_direct_text_search(query: str) -> dict | None:
    if not _should_direct_text_search(query):
        return None

    try:
        result = search_by_text_clip.invoke({"query": query, "top_k": 5})
    except Exception:
        return None

    if not isinstance(result, dict):
        return None
    return result


def _build_direct_search_answer(query: str, products: list[dict]) -> str:
    if not products:
        return f"'{query}' 조건으로 상품을 찾지 못했습니다. 다른 색상이나 표현으로 다시 찾아볼게요."

    first_product = products[0]
    name = str(first_product.get("name") or "상품")
    category = str(first_product.get("category") or "").strip()
    color = str(first_product.get("color") or "").strip()

    details = [part for part in [category, color] if part]
    if details:
        return f"'{query}'와 관련된 상품을 찾았습니다. 가장 가까운 결과는 {name} ({', '.join(details)})입니다."
    return f"'{query}'와 관련된 상품을 찾았습니다. 가장 가까운 결과는 {name}입니다."
