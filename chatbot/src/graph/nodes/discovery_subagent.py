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
from urllib.parse import urlparse
from urllib.request import urlopen

from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.schemas.planner import TaskIntent
from chatbot.src.graph.llm_providers import make_chat_llm
from chatbot.src.tools.recommendation_tools import (
    recommend_clothes,
    search_by_image,
    search_by_text_clip,
)
from chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.backend.app.uploads import CHATBOT_UPLOAD_DIR

# ── 도구 목록 (TEXT 경로) ──────────────────────────────────

DISCOVERY_TOOLS = [
    search_by_text_clip,
    recommend_clothes,
]

# ── 프롬프트 ──────────────────────────────────────────────

DISCOVERY_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 Discovery SubAgent입니다.
사용자가 원하는 상품을 찾아주는 역할을 합니다.

[도구 선택 기준]
- `search_by_text_clip`    : 텍스트 기반 스타일/무드/유사 이미지 검색.
  예) "겨울 패딩", "흰색 린넨 셔츠", "나이키 운동화"
- `recommend_clothes`      : 카테고리/용도/계절 조합의 스타일 추천.
  예) "여름에 입을 캐주얼 상의", "파티용 드레스"
  단, 카테고리(상의/하의/원피스 등)가 불명확하면 도구를 호출하지 말고 먼저 질문하세요.

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


# ── TEXT 경로 ──────────────────────────────────────────────

def _text_search_pipeline(
    state: GlobalAgentState, provider: str, model: str, task: str | None
) -> dict:
    """텍스트 기반 상품 검색: ReAct 에이전트로 도구 선택."""
    user_info = state.get("user_info", {})
    user_context = (
        f"User ID: {user_info.get('id', 'unknown')}, "
        f"Name: {user_info.get('name', '고객')}"
    )

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    agent = create_react_agent(
        model=llm,
        tools=DISCOVERY_TOOLS,
        prompt=SystemMessage(
            content=DISCOVERY_SYSTEM_PROMPT.format(user_context=user_context)
        ),
    )

    result = agent.invoke({"messages": state["messages"]})
    result_messages = result.get("messages", [])

    # 검색 결과 추출 → search_context 업데이트
    search_context = _extract_search_results(result_messages)

    # 마지막 AIMessage 내용을 agent_results 에 저장
    last_ai_content = _get_last_ai_content(result_messages)

    return {
        "messages": result_messages,
        "search_context": {**state.get("search_context", {}), **search_context},
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
