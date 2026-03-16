"""
어댑터 기반 주문 관련 Tools.

현재 주문 CS 어댑터는 ecommerce `site-c`만 정식 지원합니다.

[설계 방침]
- cancel, refund, shipping → site-c 어댑터 API 호출
- exchange, change_option, update_payment, get_user_orders → 기존 order_tools.py (Ecommerce DB 전용)

사용자 컨텍스트(AuthenticatedContext)는 LangGraph state의 user_info에서 구성합니다.
"""
import asyncio
from langchain_core.tools import tool
from langgraph.types import interrupt

from chatbot.src.adapters.schema import (
    AuthenticatedContext,
    GetOrderStatusInput,
    GetDeliveryTrackingInput,
    SubmitOrderActionInput,
    OrderActionType,
    OrderActionReason,
    AdapterError,
)
from chatbot.src.adapters.setup import get_adapter
from chatbot.src.tools.order_tools import (
    _is_langgraph_interrupt_error,
    _require_order_id,
    _resolve_order_id_or_payload,
    _require_human_confirmation,
    _extract_order_id_from_resume,
    _extract_optional_confirmation_from_resume,
    get_user_orders,
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


def _build_ctx(user_id: str, site_id: str, access_token: str | None = None) -> AuthenticatedContext:
    """LangGraph state의 user_info에서 AuthenticatedContext를 구성합니다."""
    return AuthenticatedContext(
        userId=str(user_id),
        siteId=site_id,
        accessToken=access_token,
    )


def _get_site_adapter(site_id: str | None):
    """현재는 ecommerce `site-c`만 어댑터 경로로 지원합니다."""
    effective_site_id = (site_id or "site-c").strip()
    if effective_site_id != "site-c":
        raise AdapterError("NOT_SUPPORTED", "현재 이 챗봇은 ecommerce(site-c)만 지원합니다.")
    return get_adapter("site-c")


# ─── 주문 취소 ─────────────────────────────────────────────────────────────────

@tool("cancel")
def cancel_order_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    reason: str = "단순 변심",
    confirmed: bool | None = None,
) -> dict:
    """
    주문을 취소합니다. (어댑터 기반 - 다중 사이트 지원)

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        site_id: 사이트 식별자 (site-a/site-b/site-c). state의 user_info.site_id에서 주입됩니다.
        access_token: 인증 토큰 (state의 user_info에서 주입)
        reason: 취소 사유
        confirmed: 사용자 확인 여부 (True일 경우에만 실제 처리)

    Returns:
        취소 처리 결과
    """
    try:
        resolved_order_id, selection_payload = _resolve_order_id_or_payload(
            user_id=user_id,
            order_id=order_id,
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

        # 주문 상태 사전 조회 (권한 확인 + 확인 UI용 금액 표시)
        adapter = _get_site_adapter(site_id)
        ctx = _build_ctx(user_id, adapter.site_id, access_token)

        try:
            order_result = _run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId=resolved_order_id)))
            order_amount = order_result.order.totalPrice.amount if order_result.order.totalPrice else 0.0
            order_status = order_result.order.status.value
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문 정보를 찾을 수 없습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

        # 취소 가능한 상태인지 확인
        cancellable_statuses = {"pending", "paid", "preparing"}
        if order_status not in cancellable_statuses:
            return {"error": f"현재 주문 상태({order_status})에서는 취소가 불가능합니다."}

        # 사용자 확인 요청
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
            return {"success": False, "message": "주문 취소가 중단되었습니다.", "order_id": resolved_order_id}

        # 어댑터를 통해 취소 요청
        try:
            result = _run(adapter.submit_order_action(ctx, SubmitOrderActionInput(
                orderId=resolved_order_id,
                actionType=OrderActionType.CANCEL,
                reasonCode=OrderActionReason.CHANGED_MIND,
                reasonText=reason,
            )))
            return {
                "success": result.success,
                "message": result.message or f"주문({resolved_order_id})이 성공적으로 취소되었습니다.",
                "status": result.status.value if result.status else "cancelled",
                "order_id": resolved_order_id,
            }
        except AdapterError as e:
            if e.code == "NOT_SUPPORTED":
                return {"error": f"해당 사이트({site_id})는 주문 취소 API를 지원하지 않습니다. 고객센터로 문의해주세요."}
            return {"error": f"취소 요청 실패: {e.message}"}

    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"주문 취소 실패: {str(e)}"}


# ─── 반품/환불 접수 ───────────────────────────────────────────────────────────

@tool("refund")
def register_return_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
    reason: str = "단순 변심",
    confirmed: bool | None = None,
) -> dict:
    """
    반품/환불을 접수합니다. (어댑터 기반 - 다중 사이트 지원)

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        site_id: 사이트 식별자 (state의 user_info.site_id에서 주입됩니다)
        access_token: 인증 토큰
        reason: 반품 사유
        confirmed: 사용자 확인 여부

    Returns:
        반품 접수 결과
    """
    try:
        provided_order_id = (order_id or "").strip()

        if provided_order_id:
            resolved_order_id = provided_order_id
        else:
            order_list_payload = get_user_orders(
                user_id=user_id,
                limit=5,
                days=30,
                requires_selection=True,
                action_context="refund",
            )

            if order_list_payload.get("total_orders", 0) == 0:
                return {
                    "eligible": False,
                    "ui_action": "show_order_list",
                    "ui_data": order_list_payload.get("ui_data", []),
                    "requires_selection": False,
                    "prior_action": "refund",
                    "message": order_list_payload.get("message", "환불 가능한 주문이 없습니다."),
                }

            while True:
                resume_value = interrupt({
                    "ui_action": "show_order_list",
                    "action": "select_order",
                    "message": order_list_payload.get("message", "반품할 주문을 선택해주세요."),
                    "ui_data": order_list_payload.get("ui_data", []),
                    "requires_selection": True,
                    "prior_action": "refund",
                })
                selected_order_id = _extract_order_id_from_resume(resume_value)
                inline_confirmed = _extract_optional_confirmation_from_resume(resume_value)
                if selected_order_id:
                    resolved_order_id = selected_order_id
                    if confirmed is None and inline_confirmed is not None:
                        confirmed = inline_confirmed
                    break

        adapter = _get_site_adapter(site_id)
        ctx = _build_ctx(user_id, adapter.site_id, access_token)

        # 주문 사전 조회
        try:
            order_result = _run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId=resolved_order_id)))
            order_status = order_result.order.status.value
            order_amount = order_result.order.totalPrice.amount if order_result.order.totalPrice else 0.0
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문 정보를 찾을 수 없습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

        # 환불 가능 상태 확인 (배송중/배송완료)
        refundable_statuses = {"shipped", "delivered"}
        if order_status not in refundable_statuses:
            return {"error": f"현재 주문 상태({order_status})에서는 반품/환불이 불가능합니다. (배송중/배송완료 상태에서만 가능)"}

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
            return {"success": False, "message": "반품 접수가 중단되었습니다.", "order_id": resolved_order_id}

        try:
            result = _run(adapter.submit_order_action(ctx, SubmitOrderActionInput(
                orderId=resolved_order_id,
                actionType=OrderActionType.REFUND,
                reasonCode=OrderActionReason.CHANGED_MIND,
                reasonText=reason,
            )))
            return {
                "success": result.success,
                "message": result.message or f"주문({resolved_order_id})의 반품이 접수되었습니다.",
                "status": result.status.value if result.status else "refund_requested",
                "order_id": resolved_order_id,
            }
        except AdapterError as e:
            if e.code == "NOT_SUPPORTED":
                return {"error": f"해당 사이트({site_id})는 반품/환불 API를 지원하지 않습니다. 고객센터로 문의해주세요."}
            return {"error": f"반품 접수 실패: {e.message}"}

    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"반품 접수 실패: {str(e)}"}


# ─── 배송 조회 ─────────────────────────────────────────────────────────────────

@tool("shipping")
def get_shipping_via_adapter(
    order_id: str | None = None,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """
    주문의 배송 현황과 택배사 정보를 조회합니다. (어댑터 기반 - 다중 사이트 지원)

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        site_id: 사이트 식별자 (state의 user_info.site_id에서 주입됩니다)
        access_token: 인증 토큰

    Returns:
        배송 상태, 택배사 정보, 송장번호 등
    """
    try:
        resolved_order_id, selection_payload = _resolve_order_id_or_payload(
            user_id=user_id,
            order_id=order_id,
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

        adapter = _get_site_adapter(site_id)
        ctx = _build_ctx(user_id, adapter.site_id, access_token)

        try:
            result = _run(adapter.get_delivery_tracking(ctx, GetDeliveryTrackingInput(orderId=resolved_order_id)))
            tracking = result.tracking
            return {
                "order_id": tracking.orderId,
                "status": tracking.deliveryStatus.value,
                "tracking_number": tracking.trackingNumber,
                "carrier_name": tracking.carrierName,
                "estimated_delivery": tracking.estimatedDeliveryAt,
                "last_updated_at": tracking.lastUpdatedAt,
            }
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "배송 정보를 찾을 수 없습니다. 아직 발송이 시작되지 않았을 수 있습니다."}
            return {"error": f"배송 조회 실패: {e.message}"}

    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"배송 정보 조회 실패: {str(e)}"}


# ─── 주문 상태 조회 ───────────────────────────────────────────────────────────

@tool("get_order_status_adapter")
def get_order_status_via_adapter(
    order_id: str,
    user_id: int = 1,
    site_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """
    특정 주문의 현재 상태를 조회합니다. (어댑터 기반 - 다중 사이트 지원)

    Args:
        order_id: 주문번호 (필수)
        user_id: 요청자 사용자 ID
        site_id: 사이트 식별자
        access_token: 인증 토큰

    Returns:
        주문 상태, 주문 항목, 총 결제금액 등
    """
    try:
        adapter = _get_site_adapter(site_id)
        ctx = _build_ctx(user_id, adapter.site_id, access_token)

        try:
            result = _run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId=order_id)))
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
        except AdapterError as e:
            if e.code == "NOT_FOUND":
                return {"error": "주문을 찾을 수 없습니다."}
            if e.code in ("UNAUTHORIZED", "FORBIDDEN"):
                return {"error": "본인의 주문만 조회할 수 있습니다."}
            return {"error": f"주문 조회 실패: {e.message}"}

    except Exception as e:
        if isinstance(e, AdapterError):
            return {"error": e.message}
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"주문 상태 조회 실패: {str(e)}"}


# ─── 상품 검색 ────────────────────────────────────────────────────────────────

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
    """
    상품을 검색합니다. (어댑터 기반 - 다중 사이트 지원)

    Args:
        query: 검색어
        user_id: 사용자 ID
        site_id: 사이트 식별자
        access_token: 인증 토큰
        min_price: 최솟값 필터
        max_price: 최댓값 필터
        limit: 최대 결과 수

    Returns:
        검색된 상품 목록
    """
    from chatbot.src.adapters.schema import ProductSearchFilter

    try:
        adapter = _get_site_adapter(site_id)
        ctx = _build_ctx(user_id, adapter.site_id, access_token)

        result = _run(adapter.search_products(ctx, ProductSearchFilter(
            query=query,
            minPrice=min_price,
            maxPrice=max_price,
            limit=limit,
        )))

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
