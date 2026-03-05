"""
Refund SubAgent 노드.

담당 TaskIntent:
  - ORDER_CS : 취소 / 반품(환불) / 교환 모든 주문 CS 처리

핵심 설계 원칙:
  - LLM은 "취소 vs 반품 vs 교환"을 절대 추론하지 않습니다.
  - DB에서 order.status를 조회한 결과로 Python 로직이 가능한 액션을 판단합니다.
  - LLM은 도구 선택 및 호출 순서만 결정합니다.

도구 호출 순서 (Delegation 패턴):
  1. 주문번호 없음  → get_user_orders(requires_selection=True)  → UI에 주문 목록 렌더링
  2. 주문번호 있음  → get_order_details(order_id)              → status 확인
  3. 취소 경로      → cancel_order()
  4. 반품 경로      → check_refund_eligibility() → register_return_request()
  5. 교환 경로      → check_exchange_eligibility() → register_exchange_request()
                    (배송 전 교환은 change_product_option())
  6. 주소 필요      → open_address_search() (텍스트로 묻지 않음)
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from ecommerce.chatbot.src.graph.state import GlobalAgentState
from ecommerce.chatbot.src.graph.llm_providers import make_chat_llm
from ecommerce.chatbot.src.tools.order_tools import (
    get_user_orders,
    get_order_details,
    get_shipping_details,
    cancel_order,
    check_refund_eligibility,
    register_return_request,
    check_exchange_eligibility,
    change_product_option,
    register_exchange_request,
)
from ecommerce.chatbot.src.tools.address_tools import open_address_search

# ── 도구 목록 ─────────────────────────────────────────────

REFUND_TOOLS = [
    get_user_orders,
    get_order_details,
    get_shipping_details,
    cancel_order,
    check_refund_eligibility,
    register_return_request,
    check_exchange_eligibility,
    change_product_option,
    register_exchange_request,
    open_address_search,
]

# ── 시스템 프롬프트 ───────────────────────────────────────

REFUND_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 Refund SubAgent입니다.
주문 취소, 반품(환불), 교환 요청을 처리합니다.

[절대 규칙 — DB 기반 분기]
취소/반품/교환의 구체적인 가능 여부는 절대 추측하지 마세요.
반드시 아래 도구 호출 순서를 따르세요:

1. 주문번호를 모르는 경우:
   → `get_user_orders(user_id=..., requires_selection=True, action_context="cancel|refund|exchange")` 호출
   → 절대 텍스트로 주문번호를 묻지 마세요.

2. 주문번호가 있는 경우:
   → `get_order_details(order_id=..., user_id=...)` 호출하여 status 확인
   → 반환된 can_cancel / can_return / can_exchange 필드를 보고 다음 단계 진행

3. 취소 (can_cancel=True):
   → `cancel_order()` 호출

4. 반품/환불 (can_return=True):
   → `check_refund_eligibility()` 호출 → 결과 확인 후 `register_return_request()` 호출

5. 교환 (can_exchange=True):
   → `check_exchange_eligibility()` 호출
   → pre_shipment: `change_product_option()` 호출
   → post_shipment: `register_exchange_request()` 호출

6. 주소가 필요한 경우:
   → 텍스트로 주소를 묻지 말고 즉시 `open_address_search()` 호출

[User Context]
{user_context}
"""


# ── 노드 함수 ─────────────────────────────────────────────

def refund_subagent_node(state: GlobalAgentState) -> dict:
    """
    Refund SubAgent.
    order_context 에서 주문 정보를 참조하고, 도구 호출 결과로 order_context 를 업데이트합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    user_info = state.get("user_info", {})
    task = state.get("current_active_task")

    user_context = (
        f"User ID: {user_info.get('id', 'unknown')}, "
        f"Name: {user_info.get('name', '고객')}"
    )

    # order_context 에 이미 주문번호가 있으면 프롬프트에 힌트 제공
    order_context = state.get("order_context", {})
    target_order_id = order_context.get("target_order_id")
    order_hint = (
        f"\n[현재 컨텍스트] 이미 특정된 주문번호: {target_order_id}"
        if target_order_id
        else "\n[현재 컨텍스트] 아직 주문번호가 특정되지 않았습니다."
    )

    system_prompt = (
        REFUND_SYSTEM_PROMPT.format(user_context=user_context) + order_hint
    )

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    agent = create_react_agent(
        model=llm,
        tools=REFUND_TOOLS,
        prompt=SystemMessage(content=system_prompt),
    )

    result = agent.invoke({"messages": state["messages"]})
    result_messages = result.get("messages", [])

    # 도구 결과에서 order_context 및 ui_action 업데이트
    updated_order_context, ui_action = _extract_order_context(
        result_messages, order_context
    )

    # 마지막 AIMessage 내용을 agent_results 에 저장 (Final Generator 전용)
    last_ai_content = _get_last_ai_content(result_messages)

    update: dict = {
        "messages": result_messages,
        "order_context": updated_order_context,
        "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
        "agent_results": {
            **state.get("agent_results", {}),
            task: last_ai_content,
        },
    }
    if ui_action:
        update["ui_action_required"] = ui_action

    return update


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _get_last_ai_content(messages: list) -> str:
    """마지막 AIMessage 의 텍스트 내용 반환"""
    from langchain_core.messages import AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""


def _extract_order_context(messages: list, current_context: dict) -> tuple[dict, str | None]:
    """
    도구 실행 결과에서 order_context 업데이트 정보와 ui_action 을 추출합니다.
    """
    import json
    from langchain_core.messages import ToolMessage

    updated = dict(current_context)
    ui_action: str | None = None

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            if not isinstance(data, dict):
                continue

            # 주문 목록 UI 액션
            if data.get("ui_template") == "order_list":
                ui_action = "show_order_list"

            # 주소 검색 UI 액션
            if data.get("ui_action") == "show_address_search":
                ui_action = "show_address_search"

            # 성공적으로 처리된 주문 ID 캡처
            if data.get("order_id"):
                updated["target_order_id"] = data["order_id"]

            # 처리 결과 상태 저장
            if data.get("status"):
                updated["last_action_status"] = data["status"]

        except Exception:
            continue

    return updated, ui_action
