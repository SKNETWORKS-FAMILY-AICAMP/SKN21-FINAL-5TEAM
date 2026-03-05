"""
Discovery SubAgent 노드.

담당 TaskIntent:
  - SEARCH_SIMILAR_TEXT  : 텍스트 기반 상품 검색 및 스타일 추천
  - SEARCH_SIMILAR_IMAGE : 이미지 URL 기반 유사 상품 검색 (VLM/CLIP 경로)

파이프라인 (다이어그램 기준):
  TEXT  경로: Retrieve (search_products_vector / recommend_clothes)
  IMAGE 경로: VLM(CLIP MODEL) → Retrieve (search_products_vector)

설계 원칙:
  - current_active_task 로 TEXT / IMAGE 경로를 분기.
  - IMAGE 경로: OpenAI Vision 모델로 이미지를 설명 텍스트로 변환 후 벡터 검색.
  - TEXT  경로: ReAct 에이전트로 search_products_vector / recommend_clothes 도구 선택.
  - 검색 결과는 search_context 에 저장하여 Final Generator 가 활용.
"""

from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from ecommerce.chatbot.src.graph.state import GlobalAgentState
from ecommerce.chatbot.src.schemas.planner import TaskIntent
from ecommerce.chatbot.src.graph.llm_providers import make_chat_llm
from ecommerce.chatbot.src.tools.product_tools import search_products_vector
from ecommerce.chatbot.src.tools.recommendation_tools import recommend_clothes
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client

# ── 도구 목록 (TEXT 경로) ──────────────────────────────────

DISCOVERY_TOOLS = [
    search_products_vector,
    recommend_clothes,
]

# ── 프롬프트 ──────────────────────────────────────────────

DISCOVERY_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 Discovery SubAgent입니다.
사용자가 원하는 상품을 찾아주는 역할을 합니다.

[도구 선택 기준]
- `search_products_vector` : 구체적인 상품명, 특징, 소재, 색상 등 키워드 기반 검색.
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

    # ── Step 1. VLM: 이미지 → 텍스트 설명 ──────────────────
    try:
        openai_client = get_openai_client()
        vlm_response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VLM_DESCRIBE_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=300,
        )
        image_description = (vlm_response.choices[0].message.content or "").strip()
    except Exception as e:
        content = f"이미지 분석 중 오류가 발생했습니다: {str(e)}"
        return {
            "messages": [AIMessage(content=content)],
            "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
            "agent_results": {**state.get("agent_results", {}), task: content},
        }

    # ── Step 2. Retrieve: 설명 텍스트로 벡터 검색 ──────────
    retrieval_result = search_products_vector.invoke({
        "query": image_description,
        "limit": 5,
    })

    answer = AIMessage(
        content=(
            f"이미지를 분석했습니다.\n"
            f"**분석 결과**: {image_description}\n\n"
            f"비슷한 스타일의 상품을 찾아드렸습니다."
        )
    )

    return {
        "messages": [answer],
        "search_context": {
            **state.get("search_context", {}),
            "image_url": image_url,
            "image_description": image_description,
            "retrieved_products": retrieval_result.get("ui_data", []),
        },
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
                if isinstance(data, dict) and data.get("ui_data"):
                    return {"retrieved_products": data["ui_data"]}
            except Exception:
                continue
    return {}
