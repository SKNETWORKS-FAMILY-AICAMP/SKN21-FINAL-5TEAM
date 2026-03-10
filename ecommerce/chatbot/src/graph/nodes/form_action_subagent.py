"""
FormAction SubAgent 노드.

담당 TaskIntent:
  - REGISTER_USED_ITEM  : 중고 상품 등록 (open_used_sale_form → register_used_sale)
  - WRITE_REVIEW        : 리뷰 작성 (create_review → UI 폼 렌더링)
  - REGISTER_GIFT_CARD  : 상품권 등록 (register_gift_card)

설계 원칙:
  - 폼 기반 UGC 액션은 항상 "UI 먼저" 원칙을 따릅니다.
  - 사용자에게 텍스트로 슬롯을 묻지 않고, 도구 호출로 프론트엔드 UI를 띄웁니다.
  - LLM은 도구를 선택하고 호출하는 역할만 수행합니다.
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from ecommerce.chatbot.src.graph.state import GlobalAgentState
from ecommerce.chatbot.src.schemas.planner import TaskIntent
from ecommerce.chatbot.src.graph.llm_providers import make_chat_llm
from ecommerce.chatbot.src.tools.service_tools import create_review, register_gift_card
from ecommerce.chatbot.src.tools.used_tools import open_used_sale_form, register_used_sale

# ── 도구 목록 ─────────────────────────────────────────────

FORM_ACTION_TOOLS = [
    open_used_sale_form,
    register_used_sale,
    create_review,
    register_gift_card,
]

# ── 시스템 프롬프트 ───────────────────────────────────────

FORM_ACTION_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 FormAction SubAgent입니다.
중고 상품 등록, 리뷰 작성, 상품권 등록 요청을 처리합니다.

[절대 규칙]
1. 중고 판매 등록 요청 시: 텍스트로 슬롯을 묻지 말고 즉시 `open_used_sale_form`을 호출하세요.
   - 사용자가 폼을 제출한 후에만 `register_used_sale`을 호출하세요.
2. 리뷰 작성 요청 시: rating/content를 묻지 말고 즉시 `create_review(rating=0, content="UI_REQUEST", ...)`를 호출하세요.
3. 상품권 등록 요청 시: 코드를 확인하고 즉시 `register_gift_card`를 호출하세요.

[User Context]
{user_context}
"""


# ── 노드 함수 ─────────────────────────────────────────────

def form_action_subagent_node(state: GlobalAgentState) -> dict:
    """
    FormAction SubAgent.
    current_active_task 에 따라 적절한 도구를 호출하고 UI 액션을 세팅합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    user_info = state.get("user_info", {})

    user_context = (
        f"User ID: {user_info.get('id', 'unknown')}, "
        f"Name: {user_info.get('name', '고객')}"
    )

    task = state.get("current_active_task")

    # 작업별 추가 지시 생성
    task_instruction = _build_task_instruction(task, state)

    system_prompt = FORM_ACTION_SYSTEM_PROMPT.format(user_context=user_context)
    if task_instruction:
        system_prompt += f"\n\n[현재 작업]\n{task_instruction}"

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    agent = create_react_agent(
        model=llm,
        tools=FORM_ACTION_TOOLS,
        prompt=SystemMessage(content=system_prompt),
    )

    result = agent.invoke({"messages": state["messages"]})
    result_messages = result.get("messages", [])

    # 마지막 AI 메시지에서 ui_action 추출하여 GlobalAgentState 플래그 세팅
    ui_action = _extract_ui_action(result_messages)

    # 마지막 AIMessage 내용을 agent_results 에 저장 (Final Generator 전용)
    last_ai_content = _get_last_ai_content(result_messages)
    updated_agent_results = {
        **state.get("agent_results", {}),
        task: last_ai_content,
    }

    update: dict = {
        "messages": result_messages,
        "completed_tasks": state.get("completed_tasks", []) + [task],
        "agent_results": updated_agent_results,
    }
    if ui_action:
        update["ui_action_required"] = ui_action

    return update


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _build_task_instruction(task: str | None, state: GlobalAgentState) -> str:
    """작업 유형별 추가 지시문 생성"""
    if task == TaskIntent.REGISTER_USED_ITEM:
        return "사용자가 중고 상품을 등록하려 합니다. `open_used_sale_form`을 즉시 호출하세요."
    if task == TaskIntent.WRITE_REVIEW:
        order_id = state.get("order_context", {}).get("target_order_id")
        if order_id:
            return f"사용자가 주문 {order_id}에 대한 리뷰를 작성하려 합니다. `create_review`를 즉시 호출하세요."
        return "사용자가 리뷰를 작성하려 합니다. 주문 번호를 확인 후 `create_review`를 호출하세요."
    if task == TaskIntent.REGISTER_GIFT_CARD:
        return "사용자가 상품권을 등록하려 합니다. 코드를 확인하고 `register_gift_card`를 호출하세요."
    return ""


def _get_last_ai_content(messages: list) -> str:
    """마지막 AIMessage 의 텍스트 내용 반환"""
    from langchain_core.messages import AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""


def _extract_ui_action(messages: list) -> str | None:
    """도구 실행 결과에서 ui_action 값을 추출"""
    import json
    from langchain_core.messages import ToolMessage

    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content
                data = json.loads(content) if isinstance(content, str) else content
                if isinstance(data, dict) and data.get("ui_action"):
                    return str(data["ui_action"])
            except Exception:
                continue
    return None
