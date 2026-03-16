"""
Order CS 전용 그래프 노드.

구조:
  ORDER_CS
    -> order_entry
    -> order_intent_router
    -> cancel_subagent | refund_subagent | exchange_subagent | shipping_subagent

핵심 원칙:
  - 상호배타 액션은 절대 한 에이전트에 동시에 노출하지 않습니다.
  - 액션 선택은 Python 규칙 기반으로 우선 처리합니다.
  - 각 액션 노드는 자기 툴만 호출하고, waiting_user/completed/failed를 명시적으로 기록합니다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.schemas.planner import TaskIntent
from chatbot.src.tools.adapter_order_tools import (
    cancel_order_via_adapter as cancel_order,
    get_shipping_via_adapter as get_shipping_details,
    register_return_via_adapter as register_return_request,
)
from chatbot.src.tools.order_tools import (
    change_product_option,
    register_exchange_request,
)

_ORDER_ACTIONS = {"cancel", "refund", "exchange", "shipping"}
_WAITING_UI_ACTIONS = {
    "show_order_list": "order_selection",
    "show_option_list": "new_option",
    "confirm_order_action": "confirmation",
    "show_address_search": "address",
}
_TERMINAL_SUCCESS_STATUSES = {
    "cancelled",
    "updated",
    "refunded (return requested)",
    "refund_requested",
    "no_change",
}


def order_entry_node(state: GlobalAgentState) -> dict:
    """주문 CS 공통 상태를 초기화합니다."""
    order_context = dict(state.get("order_context", {}))
    order_context.setdefault("pending_action", None)
    order_context.setdefault("action_status", "ready")
    order_context.setdefault("awaiting_resume_for", None)
    order_context.setdefault("last_tool", None)
    order_context.setdefault("last_ui_payload", None)
    return {
        "order_context": order_context,
        "ui_action_required": None,
    }


def order_intent_router_node(state: GlobalAgentState) -> dict:
    """주문 액션을 cancel/refund/exchange/shipping 중 하나로 결정합니다."""
    order_context = dict(state.get("order_context", {}))
    pending_action = str(order_context.get("pending_action") or "").strip().lower()
    awaiting_resume_for = order_context.get("awaiting_resume_for")

    if pending_action in _ORDER_ACTIONS and awaiting_resume_for:
        order_context["action_status"] = "ready"
        return {"order_context": order_context}

    latest_user_message = _get_latest_user_message(state)
    resolved_action = _classify_order_action(latest_user_message, pending_action)

    order_context["pending_action"] = resolved_action
    order_context["action_status"] = "ready"
    return {"order_context": order_context}


def route_after_order_intent_router(state: GlobalAgentState) -> str:
    action = str(state.get("order_context", {}).get("pending_action") or "").strip().lower()
    return {
        "cancel": "cancel_subagent",
        "refund": "refund_subagent",
        "exchange": "exchange_subagent",
        "shipping": "shipping_subagent",
    }.get(action, "final_generator")


def route_after_order_action(state: GlobalAgentState) -> str:
    action_status = str(state.get("order_context", {}).get("action_status") or "").strip().lower()
    if action_status == "completed":
        return "supervisor"
    return "final_generator"


def cancel_subagent_node(state: GlobalAgentState) -> dict:
    return _run_order_action(
        state=state,
        action="cancel",
        tool=cancel_order,
        include_site_context=True,
    )


def refund_subagent_node(state: GlobalAgentState) -> dict:
    return _run_order_action(
        state=state,
        action="refund",
        tool=register_return_request,
        include_site_context=True,
    )


def shipping_subagent_node(state: GlobalAgentState) -> dict:
    return _run_order_action(
        state=state,
        action="shipping",
        tool=get_shipping_details,
        include_site_context=True,
    )


def exchange_subagent_node(state: GlobalAgentState) -> dict:
    tool = _select_exchange_tool(state)
    tool_name = "change_option" if tool is change_product_option else "exchange"
    return _run_order_action(
        state=state,
        action="exchange",
        tool=tool,
        include_site_context=False,
        tool_name=tool_name,
    )


def _run_order_action(
    *,
    state: GlobalAgentState,
    action: str,
    tool: Any,
    include_site_context: bool,
    tool_name: str | None = None,
) -> dict:
    payload = _build_tool_payload(state, include_site_context=include_site_context)
    result = tool.invoke(payload)
    return _build_order_action_update(
        state=state,
        action=action,
        tool_name=tool_name or action,
        result=result,
    )


def _build_tool_payload(state: GlobalAgentState, *, include_site_context: bool) -> dict[str, Any]:
    user_info = state.get("user_info", {})
    order_context = state.get("order_context", {})

    payload: dict[str, Any] = {
        "user_id": user_info.get("id", 1),
    }

    target_order_id = order_context.get("target_order_id")
    if target_order_id:
        payload["order_id"] = target_order_id

    if order_context.get("new_option_id") is not None:
        payload["new_option_id"] = order_context["new_option_id"]

    if include_site_context:
        payload["site_id"] = user_info.get("site_id")
        payload["access_token"] = user_info.get("access_token")

    return payload


def _build_order_action_update(
    *,
    state: GlobalAgentState,
    action: str,
    tool_name: str,
    result: dict[str, Any],
) -> dict:
    order_context = dict(state.get("order_context", {}))
    order_context["pending_action"] = action
    order_context["last_tool"] = tool_name

    order_id = result.get("order_id")
    if order_id:
        order_context["target_order_id"] = order_id

    if result.get("new_option_id") is not None:
        order_context["new_option_id"] = result["new_option_id"]

    ui_action = result.get("ui_action")
    awaiting_resume_for = _WAITING_UI_ACTIONS.get(str(ui_action or "").strip(), None)

    if result.get("status"):
        order_context["last_action_status"] = result["status"]
    elif result.get("current_status"):
        order_context["last_action_status"] = result["current_status"]

    message = _extract_result_message(action, result)
    action_status = _resolve_action_status(action, result, ui_action)
    order_context["action_status"] = action_status
    order_context["awaiting_resume_for"] = awaiting_resume_for
    order_context["last_ui_payload"] = (
        _build_ui_payload(action, result)
        if action_status == "waiting_user" and ui_action
        else None
    )

    completed_tasks = list(state.get("completed_tasks", []))
    if action_status == "completed" and TaskIntent.ORDER_CS not in completed_tasks:
        completed_tasks.append(TaskIntent.ORDER_CS)

    update = {
        "order_context": order_context,
        "completed_tasks": completed_tasks,
        "agent_results": {
            **state.get("agent_results", {}),
            TaskIntent.ORDER_CS: message,
        },
        "ui_action_required": ui_action if action_status == "waiting_user" else None,
    }

    return update


def _resolve_action_status(action: str, result: dict[str, Any], ui_action: str | None) -> str:
    if ui_action:
        return "waiting_user"

    if result.get("needs_order_id") or result.get("needs_new_option"):
        return "waiting_user"

    if result.get("error"):
        return "failed"

    status = str(result.get("status", "")).strip().lower()
    current_status = str(result.get("current_status", "")).strip().lower()

    if result.get("success") is True:
        if status in _TERMINAL_SUCCESS_STATUSES:
            return "completed"
        if action == "shipping":
            return "completed"

    if "processing (exchange)" in current_status:
        return "completed"

    if status in _TERMINAL_SUCCESS_STATUSES:
        return "completed"

    return "failed"


def _extract_result_message(action: str, result: dict[str, Any]) -> str:
    if isinstance(result.get("message"), str) and result["message"].strip():
        return result["message"].strip()

    if isinstance(result.get("error"), str) and result["error"].strip():
        return result["error"].strip()

    if action == "shipping":
        status = result.get("status")
        carrier_name = result.get("carrier_name")
        tracking_number = result.get("tracking_number")
        if status:
            parts = [f"배송 상태는 {status}입니다."]
            if carrier_name:
                parts.append(f"택배사는 {carrier_name}입니다.")
            if tracking_number:
                parts.append(f"송장번호는 {tracking_number}입니다.")
            return " ".join(parts)

    return "주문 요청을 처리했습니다."


def _build_ui_payload(action: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ui_action": result.get("ui_action"),
        "ui_data": result.get("ui_data"),
        "requires_selection": result.get("requires_selection", False),
        "prior_action": result.get("prior_action", action),
        "message": _extract_result_message(action, result),
    }


def _select_exchange_tool(state: GlobalAgentState):
    order_context = state.get("order_context", {})
    awaiting_resume_for = order_context.get("awaiting_resume_for")
    latest_user_message = _get_latest_user_message(state)

    if awaiting_resume_for == "new_option":
        return change_product_option

    option_keywords = ("옵션", "사이즈", "색상", "size", "option", "변경")
    if any(keyword in latest_user_message for keyword in option_keywords):
        return change_product_option

    return register_exchange_request


def _classify_order_action(latest_user_message: str, current_action: str | None) -> str:
    text = latest_user_message.strip().lower()

    if any(keyword in text for keyword in ("배송", "언제 와", "어디쯤", "송장", "택배")):
        return "shipping"
    if any(keyword in text for keyword in ("교환", "사이즈", "옵션 변경", "옵션", "색상 변경")):
        return "exchange"
    if any(keyword in text for keyword in ("환불", "반품")):
        return "refund"
    if any(keyword in text for keyword in ("취소", "주문취소")):
        return "cancel"

    if current_action in _ORDER_ACTIONS:
        return current_action

    return "refund"


def _get_latest_user_message(state: GlobalAgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return str(msg.content).strip()
    return ""
