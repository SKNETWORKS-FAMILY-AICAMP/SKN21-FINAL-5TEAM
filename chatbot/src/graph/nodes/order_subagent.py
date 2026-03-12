"""
Refund SubAgent 노드.

담당 TaskIntent:
  - ORDER_CS : 취소 / 반품(환불) / 교환 모든 주문 CS 처리

핵심 설계 원칙:
  - LLM은 "취소 vs 반품 vs 교환"을 절대 추론하지 않습니다.
  - DB에서 order.status를 조회한 결과로 Python 로직이 가능한 액션을 판단합니다.
  - LLM은 도구 선택 및 호출 순서만 결정합니다.

도구 호출 순서 (Delegation 패턴):
        1. 취소 경로      → cancel()
        2. 반품 경로      → refund()
                                        (도구 내부에서 검증 + HITL 승인 checkpoint)
        3. 교환 경로      → exchange()
                                        (도구 내부에서 검증 + HITL 승인 checkpoint)
                                        (배송 전 교환은 change_option())
        4. 주소 필요      → open_address_search() (텍스트로 묻지 않음)

중요:
    - order_id가 없을 때 list_orders를 먼저 강제 호출하지 않습니다.
    - 액션 도구(cancel/refund/exchange/change_option/shipping/update_payment)를 바로 호출하면,
        각 도구 내부의 interrupt가 show_order_list UI를 발생시켜 주문을 수집합니다.
"""

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.graph.llm_providers import make_chat_llm

# ── 어댑터 기반 툴 (다중 사이트 지원)
from chatbot.src.tools.adapter_order_tools import (
    cancel_order_via_adapter as cancel_order,
    register_return_via_adapter as register_return_request,
    get_shipping_via_adapter as get_shipping_details,
    get_order_status_via_adapter,
)
# ── ecommerce DB 전용 툴 (교환·옵션 변경은 DB 재고 연동 필요)
from chatbot.src.tools.order_tools import (
    change_product_option,
    register_exchange_request,
)

# ── 도구 목록 ─────────────────────────────────────────────

REFUND_TOOLS = [
    get_shipping_details,
    cancel_order,
    register_return_request,
    get_order_status_via_adapter,
    change_product_option,
    register_exchange_request,
]

# ── 시스템 프롬프트 ───────────────────────────────────────

REFUND_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 Refund SubAgent입니다.
주문 취소, 반품(환불), 교환 요청을 처리합니다.

[절대 규칙 — DB 기반 분기]
취소/반품/교환의 구체적인 가능 여부는 절대 추측하지 마세요.
반드시 아래 도구 호출 순서를 따르세요:

1. 주문번호를 모르는 경우:
    → 액션 도구(`cancel`, `refund`, `exchange`, `change_option`, `shipping`, `update_payment`)를
      바로 호출하세요.
    → order_id가 없으면 각 도구 내부 checkpoint가 `show_order_list` UI로 수집합니다.
   → 절대 텍스트로 주문번호를 묻지 마세요.
     → `list_orders`를 직접 호출해 주문 선택을 처리하려고 하지 마세요.
         (주문 선택은 반드시 각 액션 도구 내부 interrupt로 처리)

2. 주문번호가 있는 경우:
    → 바로 해당 액션 도구를 호출하세요.

3. 취소 (can_cancel=True):
    → `cancel()` 호출 — user_id, site_id, access_token 반드시 전달

4. 반품/환불 (can_return=True):
    → `refund(confirmed=None)` 호출 — user_id, site_id, access_token 반드시 전달
    → 도구가 검증/금액안내 후 HITL 승인 checkpoint를 발생시킴

5. 교환 (can_exchange=True):
    → pre_shipment: `change_option()` 호출
    → post_shipment: `exchange(confirmed=None)` 호출

[User Context]
{user_context}
"""


# ── 노드 함수 ─────────────────────────────────────────────

def order_subagent_node(state: GlobalAgentState) -> dict:
    """
    Order SubAgent.
    order_context 에서 주문 정보를 참조하고, 도구 호출 결과로 order_context 를 업데이트합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    user_info = state.get("user_info", {})
    task = state.get("current_active_task")

    user_id = user_info.get("id", 1)
    site_id = user_info.get("site_id")
    access_token = user_info.get("access_token")

    user_context = (
        f"User ID: {user_id}, "
        f"Name: {user_info.get('name', '고객')}, "
        f"Site ID: {site_id or 'site-a (default)'}\n"
        f"[도구 호출 시 user_id={user_id}, site_id={site_id!r}, access_token={'(있음)' if access_token else '(없음)'} 을 반드시 전달하세요]"
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

    input_messages = list(state["messages"])
    result = agent.invoke({"messages": input_messages})
    result_messages = result.get("messages", [])
    new_messages = (
        result_messages[len(input_messages):]
        if isinstance(result_messages, list) and len(result_messages) >= len(input_messages)
        else result_messages
    )


    # 도구 결과에서 order_context 및 ui_action 업데이트
    updated_order_context, ui_action = _extract_order_context(
        new_messages, order_context
    )
    task_state = _assess_order_task_state(new_messages, ui_action)

    # 마지막 AIMessage 내용을 agent_results 에 저장 (Final Generator 전용)
    last_ai_content = _get_last_ai_content(result_messages)

    existing_completed = list(state.get("completed_tasks", []))
    completed_tasks = existing_completed
    if task and task_state == "completed" and task not in existing_completed:
        completed_tasks = existing_completed + [task]

    update: dict = {
        "messages": result_messages,
        "order_context": updated_order_context,
        "completed_tasks": completed_tasks,
        "ui_action_required": ui_action,
    }

    if task:
        update["agent_results"] = {
            **state.get("agent_results", {}),
            task: last_ai_content,
        }

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
            if data.get("ui_action") == "show_order_list":
                ui_action = "show_order_list"

            # 성공적으로 처리된 주문 ID 캡처
            if data.get("order_id"):
                updated["target_order_id"] = data["order_id"]

            # 처리 결과 상태 저장
            if data.get("status"):
                updated["last_action_status"] = data["status"]

        except Exception:
            continue

    return updated, ui_action


def _assess_order_task_state(messages: list, ui_action: str | None) -> str:
    """
    주문 CS task 상태를 판정합니다.

    Returns:
        "completed" | "waiting_user" | "failed" | "in_progress"
    """
    import json
    from langchain_core.messages import ToolMessage

    if ui_action in {"show_order_list"}:
        return "waiting_user"

    has_terminal_success = False
    has_waiting_user = False
    has_error = False

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue

        try:
            data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            if not isinstance(data, dict):
                continue

            if data.get("error"):
                has_error = True

            if data.get("needs_new_option") is True:
                has_waiting_user = True

            if data.get("success") is True:
                status = str(data.get("status", "")).strip().lower()
                current_status = str(data.get("current_status", "")).strip().lower()

                if status in {
                    "cancelled",
                    "updated",
                    "refunded (return requested)",
                    "no_change",
                }:
                    has_terminal_success = True

                if "processing (exchange)" in current_status:
                    has_terminal_success = True

        except Exception:
            continue

    if has_terminal_success:
        return "completed"
    if has_waiting_user:
        return "waiting_user"
    if has_error:
        return "failed"
    return "in_progress"
