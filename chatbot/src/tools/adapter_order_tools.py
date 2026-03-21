"""
어댑터 기반 주문 관련 Tools.

[설계 방침]
- site-a/site-c 주문 조회/취소/환불/교환/배송 조회를 어댑터 경로로 처리
- site-c 전용 재고/옵션 교환은 기존 order_tools.py가 계속 담당

사용자 컨텍스트(AuthenticatedContext)는 LangGraph state의 user_info에서 구성합니다.
"""

import asyncio
from typing import Callable

from langchain_core.tools import tool
from langgraph.types import interrupt

from chatbot.src.adapters.schema import (
    AdapterError,
    AuthenticatedContext,
    GetDeliveryTrackingInput,
    GetOrderStatusInput,
    OrderActionReason,
    OrderActionType,
    ProductSearchFilter,
    SubmitOrderActionInput,
)
from chatbot.src.adapters.setup import ORDER_CS_BRIDGE_OPERATIONS, get_adapter
from chatbot.src.tools.order_tools import (
    _extract_optional_confirmation_from_resume,
    _extract_order_id_from_resume,
    _is_langgraph_interrupt_error,
    _require_human_confirmation,
)


def _run(coro):
    """동기 컨텍스트에서 비동기 어댑터 메서드를 실행합니다."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


def _build_ctx(
    user_id: str,
    site_id: str,
    access_token: str | None = None,
) -> AuthenticatedContext:
    """LangGraph state의 user_info에서 AuthenticatedContext를 구성합니다."""
    return AuthenticatedContext(
        userId=str(user_id),
        siteId=site_id,
        accessToken=access_token,
    )


def _get_site_adapter(site_id: str | None):
    """site_id에 해당하는 어댑터를 조회합니다."""
    effective_site_id = (site_id or "site-c").strip()
    return get_adapter(effective_site_id)


def _build_auth_headers(ctx: AuthenticatedContext) -> dict[str, str]:
    if ctx.siteId == "site-a":
        from chatbot.src.adapters.site_a.auth import build_site_a_auth_headers

        return build_site_a_auth_headers(ctx)
    if ctx.siteId == "site-b":
        from chatbot.src.adapters.site_b.auth import build_site_b_auth_headers

        return build_site_b_auth_headers(ctx)
    if ctx.siteId == "site-c":
        from chatbot.src.adapters.site_c.auth import build_site_c_auth_headers

        return build_site_c_auth_headers(ctx)
    return {}


def _build_order_list_message(action_context: str | None, days: int) -> str:
    base_msg = f"최근 {days}일 이내 주문 내역입니다."
    if action_context == "refund":
        return base_msg + " 환불하실 주문을 선택해주세요."
    if action_context == "exchange":
        return base_msg + " 교환하실 주문을 선택해주세요."
    if action_context == "cancel":
        return base_msg + " 취소하실 주문을 선택해주세요."
    if action_context == "shipping":
        return base_msg + " 배송 조회하실 주문을 선택해주세요."
    return base_msg


def _normalize_site_order_status(adapter, raw_status: str) -> str:
    normalize = getattr(adapter, "_normalize_order_status", None)
    if callable(normalize):
        return normalize(raw_status).value
    return str(raw_status or "unknown").strip().lower()


def _derive_site_order_actions(
    normalized_status: str,
    payment_status: str | None,
) -> dict[str, bool]:
    normalized_payment = str(payment_status or "").strip().lower()
    if not normalized_payment and normalized_status in {"paid", "preparing", "shipped", "delivered"}:
        normalized_payment = "paid"
    is_paid = normalized_payment == "paid"
    return {
        "can_cancel": normalized_status == "preparing",
        "can_return": is_paid and normalized_status in {"shipped", "delivered"},
        "can_exchange": is_paid and normalized_status in {"shipped", "delivered"},
    }


def _build_order_ui_item(adapter, raw_order: dict) -> dict:
    normalized_status = _normalize_site_order_status(
        adapter,
        raw_order.get("status", "unknown"),
    )
    actions = _derive_site_order_actions(
        normalized_status,
        raw_order.get("payment_status"),
    )
    product = raw_order.get("product") or {}
    items = raw_order.get("items") or []
    first_item = items[0] if isinstance(items, list) and items else {}
    total_amount = raw_order.get("total_price")
    if total_amount is None:
        total_amount = raw_order.get("total_amount")
    product_name = product.get("name")
    if not product_name and isinstance(first_item, dict):
        product_name = first_item.get("product_name") or first_item.get("productTitle")
    return {
        "order_id": str(raw_order.get("id")),
        "date": str(raw_order.get("created_at", ""))[:10],
        "status": normalized_status,
        "status_label": raw_order.get("status_label") or normalized_status,
        "product_name": product_name or "상품 정보 없음",
        "amount": float(total_amount or 0),
        "delivered_at": (
            str(raw_order.get("created_at", ""))[:10]
            if normalized_status == "delivered"
            else None
        ),
        **actions,
    }


def _list_orders_via_adapter(
    adapter,
    ctx: AuthenticatedContext,
    limit: int,
) -> list[dict]:
    if hasattr(adapter, "list_orders") and callable(getattr(adapter, "list_orders")):
        raw_orders = _run(adapter.list_orders(ctx, limit=limit))
    elif hasattr(adapter, "client") and hasattr(adapter.client, "list_orders"):
        raw_orders = _run(adapter.client.list_orders(_build_auth_headers(ctx)))
    else:
        raise AdapterError(
            "NOT_SUPPORTED",
            f"해당 사이트({ctx.siteId})는 주문 목록 조회 API를 지원하지 않습니다.",
        )

    if isinstance(raw_orders, dict):
        orders = raw_orders.get("orders")
        return orders if isinstance(orders, list) else []

    return raw_orders if isinstance(raw_orders, list) else []


def _order_matches_action(order_item: dict, action_context: str | None) -> bool:
    if action_context == "refund":
        return bool(order_item.get("can_return"))
    if action_context == "exchange":
        return bool(order_item.get("can_exchange"))
    if action_context == "cancel":
        return bool(order_item.get("can_cancel"))
    return True


def get_user_orders_for_site(
    *,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    limit: int = 5,
    days: int = 30,
    requires_selection: bool = False,
    action_context: str | None = None,
) -> dict:
    effective_site_id = (site_id or "site-c").strip()
    adapter = _get_site_adapter(effective_site_id)
    ctx = _build_ctx(user_id, adapter.site_id, access_token)
    raw_list = _list_orders_via_adapter(adapter, ctx, limit)
    ui_data = [
        _build_order_ui_item(adapter, raw_order)
        for raw_order in raw_list[:limit]
        if isinstance(raw_order, dict)
    ]
    ui_data = [
        item
        for item in ui_data
        if _order_matches_action(item, action_context)
    ]

    base_msg = _build_order_list_message(action_context, days)
    if not ui_data:
        if action_context == "refund":
            msg_suffix = " (환불 가능한 주문이 없습니다.)"
        elif action_context == "exchange":
            msg_suffix = " (교환 가능한 주문이 없습니다.)"
        elif action_context == "cancel":
            msg_suffix = " (취소 가능한 주문이 없습니다.)"
        else:
            msg_suffix = " (주문 내역이 없습니다.)"
        return {
            "ui_action": "show_order_list",
            "message": base_msg + msg_suffix,
            "total_orders": 0,
            "ui_data": [],
            "requires_selection": False,
            "prior_action": action_context,
        }

    return {
        "ui_action": "show_order_list",
        "message": base_msg,
        "total_orders": len(ui_data),
        "ui_data": ui_data,
        "requires_selection": requires_selection and action_context is not None,
        "prior_action": action_context,
    }


def _normalize_order_list_bridge_payload(payload: dict) -> dict:
    return {
        "operation": "list_orders",
        "message": payload.get("message"),
        "total_orders": payload.get("total_orders", 0),
        "orders": payload.get("ui_data", []),
        "requires_selection": payload.get("requires_selection", False),
        "prior_action": payload.get("prior_action"),
    }


def _normalize_action_bridge_payload(operation: str, payload: dict) -> dict:
    if isinstance(payload, dict) and payload.get("operation") == operation:
        return payload
    normalized = dict(payload or {})
    normalized.setdefault("operation", operation)
    return normalized


def build_order_cs_bridge(
    *,
    site_id: str,
    user_id: int = 1,
    access_token: str | None = None,
) -> dict[str, Callable[..., dict]]:
    effective_site_id = (site_id or "site-c").strip()

    def list_orders(**kwargs) -> dict:
        payload = get_user_orders_for_site(
            user_id=user_id,
            site_id=effective_site_id,
            access_token=access_token,
            **kwargs,
        )
        return _normalize_order_list_bridge_payload(payload)

    def get_order_status(order_id: str, **kwargs) -> dict:
        payload = get_order_status_via_adapter.invoke(
            {
                "user_id": user_id,
                "site_id": effective_site_id,
                "access_token": access_token,
                "order_id": order_id,
                **kwargs,
            }
        )
        return _normalize_action_bridge_payload("get_order_status", payload)

    def cancel(order_id: str = "", confirmed: bool = True, **kwargs) -> dict:
        payload = cancel_order_via_adapter.invoke(
            {
                "user_id": user_id,
                "site_id": effective_site_id,
                "access_token": access_token,
                "order_id": order_id,
                "confirmed": confirmed,
                **kwargs,
            }
        )
        return _normalize_action_bridge_payload("cancel", payload)

    def refund(order_id: str = "", confirmed: bool = True, **kwargs) -> dict:
        payload = register_return_via_adapter.invoke(
            {
                "user_id": user_id,
                "site_id": effective_site_id,
                "access_token": access_token,
                "order_id": order_id,
                "confirmed": confirmed,
                **kwargs,
            }
        )
        return _normalize_action_bridge_payload("refund", payload)

    def exchange(order_id: str = "", confirmed: bool = True, **kwargs) -> dict:
        payload = register_exchange_via_adapter.invoke(
            {
                "user_id": user_id,
                "site_id": effective_site_id,
                "access_token": access_token,
                "order_id": order_id,
                "confirmed": confirmed,
                **kwargs,
            }
        )
        return _normalize_action_bridge_payload("exchange", payload)

    bridge = {
        "list_orders": list_orders,
        "get_order_status": get_order_status,
        "cancel": cancel,
        "refund": refund,
        "exchange": exchange,
    }
    return {name: bridge[name] for name in ORDER_CS_BRIDGE_OPERATIONS}


def _resolve_order_id_or_payload_for_site(
    *,
    user_id: int,
    order_id: str | None,
    site_id: str | None,
    access_token: str | None,
    action_context: str,
    limit: int = 5,
    days: int = 30,
) -> tuple[str | None, dict | None]:
    provided = (order_id or "").strip()
    if provided:
        return provided, None

    order_list_payload = get_user_orders_for_site(
        user_id=user_id,
        site_id=site_id,
        access_token=access_token,
        limit=limit,
        days=days,
        requires_selection=True,
        action_context=action_context,
    )

    if order_list_payload.get("total_orders", 0) == 0:
        return None, order_list_payload

    while True:
        resume_value = interrupt(
            {
                "ui_action": "show_order_list",
                "action": "select_order",
                "message": order_list_payload.get("message", "주문을 선택해주세요."),
                "ui_data": order_list_payload.get("ui_data", []),
                "requires_selection": True,
                "prior_action": action_context,
            }
        )
        selected_order_id = _extract_order_id_from_resume(resume_value)
        if selected_order_id:
            return selected_order_id, None


def _resolve_order_with_confirmation_for_site(
    *,
    user_id: int,
    order_id: str | None,
    site_id: str | None,
    access_token: str | None,
    action_context: str,
    confirmed: bool | None,
) -> tuple[str | None, bool | None, dict | None]:
    provided = (order_id or "").strip()
    if provided:
        return provided, confirmed, None

    order_list_payload = get_user_orders_for_site(
        user_id=user_id,
        site_id=site_id,
        access_token=access_token,
        limit=5,
        days=30,
        requires_selection=True,
        action_context=action_context,
    )

    if order_list_payload.get("total_orders", 0) == 0:
        return None, confirmed, {
            "eligible": False,
            "ui_action": "show_order_list",
            "ui_data": order_list_payload.get("ui_data", []),
            "requires_selection": False,
            "prior_action": action_context,
            "message": order_list_payload.get(
                "message",
                "처리 가능한 주문이 없습니다.",
            ),
        }

    while True:
        resume_value = interrupt(
            {
                "ui_action": "show_order_list",
                "action": "select_order",
                "message": order_list_payload.get("message", "주문을 선택해주세요."),
                "ui_data": order_list_payload.get("ui_data", []),
                "requires_selection": True,
                "prior_action": action_context,
            }
        )
        selected_order_id = _extract_order_id_from_resume(resume_value)
        inline_confirmed = _extract_optional_confirmation_from_resume(resume_value)
        if selected_order_id:
            resolved_confirmed = confirmed
            if resolved_confirmed is None and inline_confirmed is not None:
                resolved_confirmed = inline_confirmed
            return selected_order_id, resolved_confirmed, None


def _build_site_adapter_context(
    *,
    user_id: int,
    site_id: str | None,
    access_token: str | None,
):
    adapter = _get_site_adapter(site_id)
    return adapter, _build_ctx(user_id, adapter.site_id, access_token)


@tool("cancel")
def cancel_order_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    reason: str = "단순 변심",
    confirmed: bool | None = None,
) -> dict:
    """주문을 취소합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        resolved_order_id, selection_payload = _resolve_order_id_or_payload_for_site(
            user_id=user_id,
            order_id=order_id,
            site_id=site_id,
            access_token=access_token,
            action_context="cancel",
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "취소할 주문을 선택해주세요.",
            }

        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )

        try:
            order_result = _run(
                adapter.get_order_status(
                    ctx,
                    GetOrderStatusInput(orderId=resolved_order_id),
                )
            )
            order_amount = (
                order_result.order.totalPrice.amount
                if order_result.order.totalPrice
                else 0.0
            )
            order_status = order_result.order.status.value
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문 정보를 찾을 수 없습니다."}
            if e.code in ("UNAUTHORIZED", "FORBIDDEN"):
                return {"error": "로그인이 필요하거나 본인 주문만 접근할 수 있습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

        cancellable_statuses = {"pending", "paid", "preparing"}
        if order_status not in cancellable_statuses:
            return {"error": f"현재 주문 상태({order_status})에서는 취소가 불가능합니다."}

        approved = _require_human_confirmation(
            action="cancel",
            prompt=f"주문({resolved_order_id})을(를) 취소할까요?",
            context={
                "order_id": resolved_order_id,
                "reason": reason,
                "refund_amount": order_amount,
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "주문 취소가 중단되었습니다.",
                "order_id": resolved_order_id,
            }

        result = _run(
            adapter.submit_order_action(
                ctx,
                SubmitOrderActionInput(
                    orderId=resolved_order_id,
                    actionType=OrderActionType.CANCEL,
                    reasonCode=OrderActionReason.CHANGED_MIND,
                    reasonText=reason,
                ),
            )
        )
        return {
            "success": result.success,
            "message": (
                result.message
                or f"주문({resolved_order_id})이 성공적으로 취소되었습니다."
            ),
            "status": "cancelled",
            "order_id": resolved_order_id,
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"주문 취소 실패: {str(e)}"}


@tool("refund")
def register_return_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    reason: str = "단순 변심",
    confirmed: bool | None = None,
) -> dict:
    """반품/환불을 접수합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        resolved_order_id, confirmed, selection_payload = (
            _resolve_order_with_confirmation_for_site(
                user_id=user_id,
                order_id=order_id,
                site_id=site_id,
                access_token=access_token,
                action_context="refund",
                confirmed=confirmed,
            )
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "환불할 주문을 선택해주세요.",
            }

        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )

        try:
            order_result = _run(
                adapter.get_order_status(
                    ctx,
                    GetOrderStatusInput(orderId=resolved_order_id),
                )
            )
            order_status = order_result.order.status.value
            order_amount = (
                order_result.order.totalPrice.amount
                if order_result.order.totalPrice
                else 0.0
            )
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문 정보를 찾을 수 없습니다."}
            if e.code in ("UNAUTHORIZED", "FORBIDDEN"):
                return {"error": "로그인이 필요하거나 본인 주문만 접근할 수 있습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

        refundable_statuses = {"shipped", "delivered"}
        if order_status not in refundable_statuses:
            return {
                "error": (
                    f"현재 주문 상태({order_status})에서는 반품/환불이 불가능합니다. "
                    "(배송중/배송완료 상태에서만 가능)"
                )
            }

        approved = _require_human_confirmation(
            action="refund",
            prompt=f"주문({resolved_order_id})의 반품을 접수할까요?",
            context={
                "order_id": resolved_order_id,
                "reason": reason,
                "refund_amount": order_amount,
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "반품 접수가 중단되었습니다.",
                "order_id": resolved_order_id,
            }

        result = _run(
            adapter.submit_order_action(
                ctx,
                SubmitOrderActionInput(
                    orderId=resolved_order_id,
                    actionType=OrderActionType.REFUND,
                    reasonCode=OrderActionReason.CHANGED_MIND,
                    reasonText=reason,
                ),
            )
        )
        return {
            "success": result.success,
            "message": (
                result.message
                or f"주문({resolved_order_id})의 반품이 접수되었습니다."
            ),
            "status": "refund_requested",
            "order_id": resolved_order_id,
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"반품 접수 실패: {str(e)}"}


@tool("exchange")
def register_exchange_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    reason: str = "교환 요청",
    confirmed: bool | None = None,
) -> dict:
    """교환을 접수합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        resolved_order_id, confirmed, selection_payload = (
            _resolve_order_with_confirmation_for_site(
                user_id=user_id,
                order_id=order_id,
                site_id=site_id,
                access_token=access_token,
                action_context="exchange",
                confirmed=confirmed,
            )
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "교환할 주문을 선택해주세요.",
            }

        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )

        try:
            order_result = _run(
                adapter.get_order_status(
                    ctx,
                    GetOrderStatusInput(orderId=resolved_order_id),
                )
            )
            order_status = order_result.order.status.value
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문 정보를 찾을 수 없습니다."}
            if e.code in ("UNAUTHORIZED", "FORBIDDEN"):
                return {"error": "로그인이 필요하거나 본인 주문만 접근할 수 있습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

        exchangeable_statuses = {"shipped", "delivered"}
        if order_status not in exchangeable_statuses:
            return {
                "error": (
                    f"현재 주문 상태({order_status})에서는 교환이 불가능합니다. "
                    "(배송중/배송완료 상태에서만 가능)"
                )
            }

        approved = _require_human_confirmation(
            action="exchange",
            prompt=f"주문({resolved_order_id})의 교환을 접수할까요?",
            context={
                "order_id": resolved_order_id,
                "reason": reason,
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "교환 접수가 중단되었습니다.",
                "order_id": resolved_order_id,
            }

        result = _run(
            adapter.submit_order_action(
                ctx,
                SubmitOrderActionInput(
                    orderId=resolved_order_id,
                    actionType=OrderActionType.EXCHANGE,
                    reasonCode=OrderActionReason.CHANGED_MIND,
                    reasonText=reason,
                ),
            )
        )
        return {
            "success": result.success,
            "message": (
                result.message
                or f"주문({resolved_order_id})의 교환이 접수되었습니다."
            ),
            "status": "exchange_requested",
            "order_id": resolved_order_id,
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"교환 접수 실패: {str(e)}"}


@tool("shipping")
def get_shipping_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """주문의 배송 현황과 택배사 정보를 조회합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        resolved_order_id, selection_payload = _resolve_order_id_or_payload_for_site(
            user_id=user_id,
            order_id=order_id,
            site_id=site_id,
            access_token=access_token,
            action_context="shipping",
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "배송 조회할 주문을 선택해주세요.",
            }

        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )

        result = _run(
            adapter.get_delivery_tracking(
                ctx,
                GetDeliveryTrackingInput(orderId=resolved_order_id),
            )
        )
        tracking = result.tracking
        return {
            "order_id": tracking.orderId,
            "status": tracking.deliveryStatus.value,
            "tracking_number": tracking.trackingNumber,
            "carrier_name": tracking.carrierName,
            "estimated_delivery": tracking.estimatedDeliveryAt,
            "last_updated_at": tracking.lastUpdatedAt,
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            if e.code == "NOT_FOUND":
                return {
                    "error": (
                        "배송 정보를 찾을 수 없습니다. 아직 발송이 시작되지 않았을 수 있습니다."
                    )
                }
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"배송 정보 조회 실패: {str(e)}"}


@tool("get_order_status_adapter")
def get_order_status_via_adapter(
    order_id: str,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """특정 주문의 현재 상태를 조회합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )
        result = _run(
            adapter.get_order_status(
                ctx,
                GetOrderStatusInput(orderId=order_id),
            )
        )
        order = result.order
        return {
            "order_id": order.orderId,
            "status": order.status.value,
            "user_id": order.userId,
            "items": [
                {
                    "product_id": item.productId,
                    "product_name": item.productTitle,
                    "quantity": item.quantity,
                    "price": item.unitPrice.amount if item.unitPrice else None,
                }
                for item in order.items
            ],
            "total_amount": order.totalPrice.amount if order.totalPrice else None,
            "ordered_at": order.orderedAt,
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            if e.code == "NOT_FOUND":
                return {"error": "주문을 찾을 수 없습니다."}
            if e.code in ("UNAUTHORIZED", "FORBIDDEN"):
                return {"error": "본인의 주문만 조회할 수 있습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"주문 상태 조회 실패: {str(e)}"}


@tool("search_products_adapter")
def search_products_via_adapter(
    query: str,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 10,
) -> dict:
    """상품을 검색합니다. (어댑터 기반 - 다중 사이트 지원)"""
    try:
        adapter, ctx = _build_site_adapter_context(
            user_id=user_id,
            site_id=site_id,
            access_token=access_token,
        )
        result = _run(
            adapter.search_products(
                ctx,
                ProductSearchFilter(
                    query=query,
                    minPrice=min_price,
                    maxPrice=max_price,
                    limit=limit,
                ),
            )
        )

        return {
            "total": result.total,
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "description": item.shortDescription,
                    "price": item.price.amount if item.price else None,
                    "currency": item.price.currency if item.price else "KRW",
                    "in_stock": item.inStock,
                    "image_url": item.imageUrl,
                    "brand": item.brand,
                }
                for item in result.items
            ],
        }
    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"상품 검색 실패: {str(e)}"}
