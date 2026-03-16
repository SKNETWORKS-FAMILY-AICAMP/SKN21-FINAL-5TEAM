"""
배송 및 주문 관련 Tools.
(Real DB Version)
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from langgraph.types import interrupt

from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.models import (
    Order,
    User,
    ProductOption,
    UsedProductOption,
)
from ecommerce.backend.app.router.orders.schemas import (
    OrderStatus,
    ProductType,
)
from ecommerce.backend.app.router.inventories.models import (
    InventoryTransaction,
    TransactionType,
    ProductType as InvProductType,
)
from ecommerce.backend.app.router.user_history.crud import (
    track_order_action,
)
from ecommerce.backend.app.router.user_history.schemas import (
    ActionType as HistoryActionType,
)


def get_db():
    """DB 세션 생성 (generator)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================
# Helper Functions (Internal Use)
# ============================================

# [Performance Optimization] 메모리 캐시 (단일 턴 내 중복 조회 방지)
_order_cache: dict[str, tuple[Order, datetime]] = {}
CACHE_TTL_SECONDS = 60  # 캐시 유효 시간: 60초


def _is_langgraph_interrupt_error(error: Exception) -> bool:
    """LangGraph interrupt 예외 여부를 안전하게 판별합니다."""
    name = error.__class__.__name__
    if name in {"GraphInterrupt", "NodeInterrupt"}:
        return True
    return "Interrupt(value=" in str(error)


def _get_order_with_auth(
    db: Session, order_id: str, user_id: int
) -> tuple[Order | None, dict | None]:
    """
    주문을 조회하고 권한을 체크합니다. (캐싱 적용)

    Args:
        db: DB 세션
        order_id: 주문번호
        user_id: 요청자 사용자 ID

    Returns:
        (Order 객체, None) 성공 시
        (None, error dict) 실패 시
    """

    # 1. 캐시 확인
    cache_key = f"{user_id}:{order_id}"
    if cache_key in _order_cache:
        cached_order, cached_at = _order_cache[cache_key]
        age = (datetime.now() - cached_at).total_seconds()
        if age < CACHE_TTL_SECONDS:
            print(f"[Cache HIT] order_id={order_id}, age={age:.1f}s")
            return cached_order, None
        else:
            # 캐시 만료
            del _order_cache[cache_key]

    # 2. DB 조회
    order = (
        db.query(Order)
        .options(joinedload(Order.shipping_info), joinedload(Order.items))
        .filter(Order.order_number == order_id)
        .first()
    )

    if not order:
        return None, {"error": "주문 정보를 찾을 수 없습니다."}

    # [Security] Authorization Check
    if order.user_id != user_id:
        return None, {"error": "PERMISSION_DENIED: 본인의 주문만 접근할 수 있습니다."}

    # 3. 캐시 저장
    _order_cache[cache_key] = (order, datetime.now())
    print(f"[Cache MISS] order_id={order_id}, cached.")

    return order, None


def _get_order_actions(order: Order) -> dict:
    """
    주문의 가능한 액션(취소/반품/교환)을 판단합니다.

    Args:
        order: Order 객체

    Returns:
        취소/반품/교환 가능 여부 및 사유
    """
    actions = {
        "can_cancel": False,
        "can_return": False,
        "can_exchange": False,
        "cancel_reason": None,
        "return_reason": None,
        "exchange_reason": None,
        "exchange_type": None,  # pre_shipment / post_shipment
    }

    # 1. 취소 가능 여부 (결제 완료, 상품 준비중)
    if order.status in [OrderStatus.PAID, OrderStatus.PREPARING]:
        actions["can_cancel"] = True

    # 2. 반품 가능 여부 (배송 후)
    if order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
        # 배송완료 상태인 경우 7일 제한 확인
        if order.status == OrderStatus.DELIVERED and order.shipping_info:
            is_valid, error_msg = _check_return_period(order.shipping_info.delivered_at)
            if is_valid:
                actions["can_return"] = True
            else:
                actions["return_reason"] = error_msg
        else:
            # SHIPPED 상태에서는 반품 접수 가능 (단, 배송완료 후 수거)
            actions["can_return"] = True


    # 3. 교환 가능 여부 (배송 전/후)
    if order.status not in [OrderStatus.CANCELLED, OrderStatus.REFUNDED]:
        if order.status in [OrderStatus.PAID, OrderStatus.PREPARING]:
            actions["can_exchange"] = True
            actions["exchange_type"] = "pre_shipment"
        elif order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            if order.status == OrderStatus.DELIVERED and order.shipping_info:
                is_valid, error_msg = _check_return_period(
                    order.shipping_info.delivered_at
                )
                if is_valid:
                    actions["can_exchange"] = True
                    actions["exchange_type"] = "post_shipment"
                else:
                    actions["exchange_reason"] = error_msg
            else:
                actions["can_exchange"] = True
                actions["exchange_type"] = "post_shipment"

    return actions


def _check_return_period(delivered_at: datetime | None) -> tuple[bool, str | None]:
    """
    배송완료일로부터 7일 이내인지 검증합니다.

    Args:
        delivered_at: 배송완료 일시

    Returns:
        (검증 성공 여부, 에러 메시지)
    """
    if not delivered_at:
        return False, "배송완료 정보가 없습니다. 배송 완료 후 환불/교환이 가능합니다."

    days_since_delivery = (datetime.now() - delivered_at).days

    if days_since_delivery > 7:
        return (
            False,
            f"배송완료일로부터 7일이 경과하여 환불/교환이 불가능합니다. (배송완료: {delivered_at.strftime('%Y-%m-%d')}, 경과일: {days_since_delivery}일)",
        )

    return True, None


def _resolve_confirmation_from_resume(resume_value: object) -> bool:
    extracted = _extract_optional_confirmation_from_resume(resume_value)
    if extracted is not None:
        return extracted

    return False


def _extract_optional_confirmation_from_resume(resume_value: object) -> bool | None:
    if isinstance(resume_value, bool):
        return resume_value

    if isinstance(resume_value, dict):
        for key in ("approved", "confirmed", "confirm", "proceed"):
            if key in resume_value:
                raw = resume_value.get(key)
                if isinstance(raw, bool):
                    return raw

    return None


def _extract_order_id_from_resume(resume_value: object) -> str | None:
    if isinstance(resume_value, dict):
        for key in ("selected_order_id", "order_id", "selectedOrderId"):
            value = resume_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _extract_new_option_id_from_resume(resume_value: object) -> int | None:
    if not isinstance(resume_value, dict):
        return None

    for key in (
        "new_option_id",
        "selected_option_id",
        "option_id",
        "selectedOptionId",
    ):
        value = resume_value.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

    return None


def _require_human_confirmation(
    *,
    action: str,
    prompt: str,
    context: dict,
    confirmed: bool | None,
) -> bool:
    """
    confirmed 값이 명시되지 않은 경우 LangGraph interrupt(checkpoint)로 사용자 확인을 받습니다.
    """
    if confirmed is not None:
        return confirmed

    resume_value = interrupt(
        {
            "ui_action": "confirm_order_action",
            "action": action,
            "message": prompt,
            **context,
        }
    )
    return _resolve_confirmation_from_resume(resume_value)


def _require_order_id(
    *,
    user_id: int,
    order_id: str | None,
    action_context: str,
    limit: int = 5,
    days: int = 30,
) -> str | None:
    provided = (order_id or "").strip()
    if provided:
        return provided

    order_list_payload = get_user_orders(
        user_id=user_id,
        limit=limit,
        days=days,
        requires_selection=True,
        action_context=action_context,
    )

    if order_list_payload.get("total_orders", 0) == 0:
        return None

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
            return selected_order_id


def _resolve_order_id_or_payload(
    *,
    user_id: int,
    order_id: str | None,
    action_context: str,
    limit: int = 5,
    days: int = 30,
) -> tuple[str | None, dict | None]:
    """주문번호를 해결하거나, 선택용 UI payload를 반환합니다."""
    provided = (order_id or "").strip()
    if provided:
        return provided, None

    order_list_payload = get_user_orders(
        user_id=user_id,
        limit=limit,
        days=days,
        requires_selection=True,
        action_context=action_context,
    )

    if order_list_payload.get("total_orders", 0) == 0:
        return None, {
            "ui_action": "show_order_list",
            "message": order_list_payload.get("message", "주문 내역이 없습니다."),
            "ui_data": order_list_payload.get("ui_data", []),
            "requires_selection": False,
            "prior_action": action_context,
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
        if selected_order_id:
            return selected_order_id, None


def _build_exchange_option_candidates(db: Session, order: Order) -> list[dict]:
    """주문과 동일 상품군의 교환 가능 옵션 목록(UI 표시용)을 구성합니다."""
    if not order.items:
        return []

    item_types = {item.product_option_type for item in order.items}
    if len(item_types) != 1:
        return []

    item_type = order.items[0].product_option_type
    current_option_ids = {int(item.product_option_id) for item in order.items}

    candidates: list[dict] = []

    if item_type == ProductType.NEW:
        first_current = (
            db.query(ProductOption)
            .filter(ProductOption.id == order.items[0].product_option_id)
            .first()
        )
        if not first_current:
            return []

        options = (
            db.query(ProductOption)
            .filter(ProductOption.product_id == first_current.product_id)
            .filter(ProductOption.is_active.is_(True))
            .order_by(ProductOption.id.asc())
            .all()
        )

        for opt in options:
            qty = int(opt.quantity or 0)
            if qty <= 0:
                continue
            size = (opt.size_name or "-").strip()
            color = (opt.color or "-").strip()
            candidates.append(
                {
                    "option_id": int(opt.id),
                    "label": f"옵션 {opt.id} · 사이즈 {size} · 색상 {color} · 재고 {qty}",
                    "size_name": opt.size_name,
                    "color": opt.color,
                    "quantity": qty,
                    "is_current": int(opt.id) in current_option_ids,
                }
            )
    else:
        first_current = (
            db.query(UsedProductOption)
            .filter(UsedProductOption.id == order.items[0].product_option_id)
            .first()
        )
        if not first_current:
            return []

        options = (
            db.query(UsedProductOption)
            .filter(UsedProductOption.used_product_id == first_current.used_product_id)
            .filter(UsedProductOption.is_active.is_(True))
            .order_by(UsedProductOption.id.asc())
            .all()
        )

        for opt in options:
            qty = int(opt.quantity or 0)
            if qty <= 0:
                continue
            size = (opt.size_name or "-").strip()
            color = (opt.color or "-").strip()
            candidates.append(
                {
                    "option_id": int(opt.id),
                    "label": f"옵션 {opt.id} · 사이즈 {size} · 색상 {color} · 재고 {qty}",
                    "size_name": opt.size_name,
                    "color": opt.color,
                    "quantity": qty,
                    "is_current": int(opt.id) in current_option_ids,
                }
            )

    # 현재 옵션은 하단으로 이동
    candidates.sort(key=lambda x: (x.get("is_current") is True, x.get("option_id", 0)))
    return candidates


def _require_new_option_id(
    *,
    db: Session,
    order: Order,
    action_context: str,
    new_option_id: int | None,
) -> int | None:
    if new_option_id is not None:
        return new_option_id

    option_candidates = _build_exchange_option_candidates(db, order)
    if not option_candidates:
        return None

    while True:
        resume_value = interrupt(
            {
                "ui_action": "show_option_list",
                "action": "select_option",
                "message": "교환할 옵션을 선택해주세요.",
                "ui_data": option_candidates,
                "requires_selection": True,
                "prior_action": action_context,
            }
        )
        selected_option_id = _extract_new_option_id_from_resume(resume_value)
        if selected_option_id is not None:
            return selected_option_id


def _resolve_default_pickup_address(db: Session, user_id: int, order: Order) -> str:
    """사용자의 기본 배송지(우선) 또는 주문 배송지로 반품/교환 수거지를 결정합니다."""
    from ecommerce.backend.app.router.shipping.models import ShippingAddress

    # 1) 사용자 기본 배송지 우선
    default_address = (
        db.query(ShippingAddress)
        .filter(ShippingAddress.user_id == user_id)
        .filter(ShippingAddress.is_default.is_(True))
        .filter(ShippingAddress.deleted_at.is_(None))
        .first()
    )

    if default_address:
        addr_parts = [p for p in [default_address.address1, default_address.address2] if p]
        return " ".join(addr_parts)

    # 2) 주문 시 사용한 배송지
    order_address = (
        db.query(ShippingAddress)
        .filter(ShippingAddress.id == order.shipping_address_id)
        .filter(ShippingAddress.deleted_at.is_(None))
        .first()
    )
    if order_address:
        addr_parts = [p for p in [order_address.address1, order_address.address2] if p]
        return " ".join(addr_parts)

    # 3) 사용자 최근 배송지 fallback
    recent_address = (
        db.query(ShippingAddress)
        .filter(ShippingAddress.user_id == user_id)
        .filter(ShippingAddress.deleted_at.is_(None))
        .order_by(ShippingAddress.created_at.desc())
        .first()
    )
    if recent_address:
        addr_parts = [p for p in [recent_address.address1, recent_address.address2] if p]
        return " ".join(addr_parts)

    return "주문 시 입력한 배송지"


def _validate_exchange_option_stock(
    db: Session, order: Order, new_option_id: int | None
) -> tuple[dict | None, dict | None]:
    """
    교환 대상 옵션 유효성/재고를 검증합니다.

    Returns:
        (validation_info, None) 성공 시
        (None, response_dict) 실패 시
    """
    if new_option_id is None:
        return None, {
            "eligible": False,
            "needs_new_option": True,
            "message": "교환할 옵션을 선택해주세요. (new_option_id 필요)",
        }

    if not order.items:
        return None, {"error": "주문 상품이 없어 교환을 진행할 수 없습니다."}

    item_types = {item.product_option_type for item in order.items}
    if len(item_types) != 1:
        return None, {
            "error": "서로 다른 상품 유형이 섞인 주문은 자동 교환이 어렵습니다. 고객센터로 문의해주세요."
        }

    item_type = order.items[0].product_option_type
    matching_items = []
    required_qty = 0
    old_option_qty_map: dict[int, int] = {}

    if item_type == ProductType.NEW:
        new_option = (
            db.query(ProductOption).filter(ProductOption.id == new_option_id).first()
        )
        if not new_option:
            return None, {"error": f"선택한 옵션(ID: {new_option_id})을 찾을 수 없습니다."}

        for item in order.items:
            current_option = (
                db.query(ProductOption)
                .filter(ProductOption.id == item.product_option_id)
                .first()
            )
            if current_option and current_option.product_id == new_option.product_id:
                matching_items.append(item)
                required_qty += item.quantity
                old_option_qty_map[item.product_option_id] = (
                    old_option_qty_map.get(item.product_option_id, 0) + item.quantity
                )

        if not matching_items:
            return None, {
                "error": "선택한 옵션은 해당 주문 상품과 일치하지 않습니다. 동일 상품의 옵션을 선택해주세요."
            }

    else:
        new_option = (
            db.query(UsedProductOption)
            .filter(UsedProductOption.id == new_option_id)
            .first()
        )
        if not new_option:
            return None, {"error": f"선택한 옵션(ID: {new_option_id})을 찾을 수 없습니다."}

        for item in order.items:
            current_option = (
                db.query(UsedProductOption)
                .filter(UsedProductOption.id == item.product_option_id)
                .first()
            )
            if (
                current_option
                and current_option.used_product_id == new_option.used_product_id
            ):
                matching_items.append(item)
                required_qty += item.quantity
                old_option_qty_map[item.product_option_id] = (
                    old_option_qty_map.get(item.product_option_id, 0) + item.quantity
                )

        if not matching_items:
            return None, {
                "error": "선택한 옵션은 해당 주문 상품과 일치하지 않습니다. 동일 상품의 옵션을 선택해주세요."
            }

    if required_qty <= 0:
        return None, {"error": "교환 대상 수량을 확인할 수 없습니다."}

    available_qty = int(new_option.quantity)
    if available_qty < required_qty:
        return None, {
            "eligible": False,
            "new_option_id": new_option_id,
            "required_quantity": required_qty,
            "available_quantity": available_qty,
            "message": f"선택한 옵션의 재고가 부족합니다. (필요: {required_qty}, 재고: {available_qty})",
        }

    return {
        "item_type": item_type,
        "new_option": new_option,
        "new_option_id": new_option_id,
        "matching_items": matching_items,
        "required_quantity": required_qty,
        "available_quantity": available_qty,
        "old_option_qty_map": old_option_qty_map,
    }, None


@tool("cancel")
def cancel_order(
    order_id: str | None = None,
    user_id: int = 1,
    reason: str = "단순 변심",
    confirmed: bool | None = None,
) -> dict:
    """
    주문을 즉시 취소합니다. (주의: 배송 시작 전 단계에서만 사용 가능)

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 취소 사유
        confirmed: 사용자 확인 여부 (True일 경우에만 실제 DB 반영)

    Returns:
        취소 처리 결과 (성공 여부, 메시지 등)
    """
    db = SessionLocal()
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

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        if order.status not in [OrderStatus.PAID, OrderStatus.PREPARING]:
            return {
                "error": "주문 취소는 결제 완료 또는 상품준비중 상태에서만 가능합니다."
            }

        approved = _require_human_confirmation(
            action="cancel",
            prompt=f"주문({resolved_order_id})을(를) 취소할까요?",
            context={
                "order_id": resolved_order_id,
                "reason": reason,
                "refund_amount": float(order.total_amount),
            },
            confirmed=confirmed,
        )

        if not approved:
            return {"success": False, "message": "주문 취소가 중단되었습니다.", "order_id": resolved_order_id}

        # 재고 복구
        for item in order.items:
            if item.product_option_type == ProductType.NEW:
                option = (
                    db.query(ProductOption)
                    .filter(ProductOption.id == item.product_option_id)
                    .first()
                )
            else:
                option = (
                    db.query(UsedProductOption)
                    .filter(UsedProductOption.id == item.product_option_id)
                    .first()
                )

            if option:
                option.quantity += item.quantity

                # 재고 거래 내역 기록
                inv_type = (
                    InvProductType.NEW
                    if item.product_option_type == ProductType.NEW
                    else InvProductType.USED
                )
                db.add(
                    InventoryTransaction(
                        product_option_type=inv_type,
                        product_option_id=item.product_option_id,
                        quantity_change=item.quantity,
                        transaction_type=TransactionType.RETURN,
                        reference_id=order.id,
                        notes=f"챗봇 주문 취소 (주문번호: {order.order_number})",
                    )
                )

        order.status = OrderStatus.CANCELLED
        order.shipping_request = f"Cancelled by user: {reason}"
        db.commit()

        # user history 기록
        try:
            user = db.query(User).filter(User.id == user_id).first()
            order_item_names = []
            for item in order.items:
                if item.product_option_type == ProductType.NEW:
                    option = (
                        db.query(ProductOption)
                        .filter(ProductOption.id == item.product_option_id)
                        .first()
                    )
                    if option and option.product:
                        order_item_names.append(option.product.name)
                else:
                    option = (
                        db.query(UsedProductOption)
                        .filter(UsedProductOption.id == item.product_option_id)
                        .first()
                    )
                    if option and option.used_product:
                        order_item_names.append(option.used_product.name)
            track_order_action(
                db,
                user_id,
                order.id,
                HistoryActionType.ORDER_DEL,
                user_name=user.name if user else None,
                order_item_name=", ".join(order_item_names)
                if order_item_names
                else None,
            )
        except Exception:
            pass  # 히스토리 기록 실패해도 취소 결과에 영향 없음

        return {
            "success": True,
            "message": f"주문({resolved_order_id})이 성공적으로 취소되었습니다.",
            "status": "cancelled",
            "refund_amount": float(order.total_amount),
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"주문 취소 실패: {str(e)}"}
    finally:
        db.close()


@tool("refund")
def register_return_request(
    order_id: str | None = None,
    user_id: int = 1,
    reason: str = "단순 변심",
    is_seller_fault: bool = False,
    pickup_address: str | None = None,
    confirmed: bool | None = None,
) -> dict:
    """
    반품을 접수합니다 (배송 후 수거).

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 반품 사유
        is_seller_fault: 판매자 귀책 여부 (True면 반품 배송비 0원)
        pickup_address: (선택) 반품 수거지 주소. 입력되지 않은 경우 주문 시 배송지를 사용합니다.
        confirmed: 사용자 확인 여부. None이면 checkpoint로 승인 요청을 발생시킵니다.

    Returns:
        반품 접수 결과
    """
    db = SessionLocal()
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
                    "needs_order_id": False,
                    "ui_action": "show_order_list",
                    "ui_data": order_list_payload.get("ui_data", []),
                    "requires_selection": False,
                    "prior_action": "refund",
                    "message": order_list_payload.get(
                        "message", "환불 가능한 주문이 없습니다."
                    ),
                }

            while True:
                resume_value = interrupt(
                    {
                        "ui_action": "show_order_list",
                        "action": "select_order",
                        "message": order_list_payload.get(
                            "message", "반품할 주문을 선택해주세요."
                        ),
                        "ui_data": order_list_payload.get("ui_data", []),
                        "requires_selection": True,
                        "prior_action": "refund",
                        "collect_confirmation": True,
                        "confirmation_message": "선택한 주문으로 반품 접수를 진행할까요?",
                    }
                )

                selected_order_id = _extract_order_id_from_resume(resume_value)
                inline_confirmed = _extract_optional_confirmation_from_resume(resume_value)

                if selected_order_id:
                    resolved_order_id = selected_order_id
                    if confirmed is None and inline_confirmed is not None:
                        confirmed = inline_confirmed
                    break

        # 캐시 무효화 (이전 세션에서 detached된 객체 방지)
        _order_cache.pop(f"{user_id}:{resolved_order_id}", None)

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        status = order.status

        if status in [OrderStatus.PAID, OrderStatus.PREPARING]:
            return {
                "eligible": False,
                "order_id": resolved_order_id,
                "current_status": status.value,
                "cancel_available": True,
                "message": (
                    f"현재 주문 상태({status.label})에서는 반품(환불) 접수가 불가능합니다. "
                    "배송 전 상태이므로 주문 취소를 이용해주세요."
                ),
            }

        if status not in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return {
                "eligible": False,
                "error": f"현재 주문 상태({status.value})에서는 반품 처리가 불가능합니다.",
            }

        if status == OrderStatus.DELIVERED:
            delivered_at = order.shipping_info.delivered_at if order.shipping_info else None
            is_valid, error_msg = _check_return_period(delivered_at)
            if not is_valid:
                return {"error": error_msg}

        if not pickup_address:
            pickup_address = _resolve_default_pickup_address(db, user_id, order)

        shipping_fee = float(order.shipping_fee)
        if is_seller_fault:
            return_shipping_fee = 0.0
            responsibility = "판매자"
        else:
            return_shipping_fee = shipping_fee * 2
            responsibility = "구매자"

        final_refund = max(0.0, float(order.total_amount) - return_shipping_fee)

        approved = _require_human_confirmation(
            action="refund",
            prompt=(
                "반품 접수를 진행할까요? "
                f"(귀책사유: {responsibility}, 반품 배송비: {return_shipping_fee:,.0f}원, "
                f"최종 환불 예정금액: {final_refund:,.0f}원)"
            ),
            context={
                "order_id": resolved_order_id,
                "reason": reason,
                "is_seller_fault": is_seller_fault,
                "responsibility": responsibility,
                "pickup_address": pickup_address,
                "return_shipping_fee": return_shipping_fee,
                "final_refund_amount": final_refund,
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "반품 접수가 취소되었습니다.",
                "order_id": resolved_order_id,
            }

        # 재고 복구
        for item in order.items:
            if item.product_option_type == ProductType.NEW:
                option = (
                    db.query(ProductOption)
                    .filter(ProductOption.id == item.product_option_id)
                    .first()
                )
            else:
                option = (
                    db.query(UsedProductOption)
                    .filter(UsedProductOption.id == item.product_option_id)
                    .first()
                )

            if option:
                option.quantity += item.quantity

                # 재고 거래 내역 기록
                inv_type = (
                    InvProductType.NEW
                    if item.product_option_type == ProductType.NEW
                    else InvProductType.USED
                )
                db.add(
                    InventoryTransaction(
                        product_option_type=inv_type,
                        product_option_id=item.product_option_id,
                        quantity_change=item.quantity,
                        transaction_type=TransactionType.RETURN,
                        reference_id=order.id,
                        notes=f"챗봇 반품 환불 (주문번호: {order.order_number})",
                    )
                )

        # 반품 접수 상태로 변경 (REFUNDED로 바로 가는 것이 아니라, 반품 요청 상태로 둬야 하지만
        # 현재 모델에는 RETURN_REQUESTED 상태가 없으므로 REFUNDED로 처리하되 메모를 남김)
        order.status = OrderStatus.REFUNDED
        order.shipping_request = f"Return Requested. Pickup: {pickup_address}"
        db.commit()

        # user history 기록
        try:
            user = db.query(User).filter(User.id == user_id).first()
            order_item_names = []
            for item in order.items:
                if item.product_option_type == ProductType.NEW:
                    option = (
                        db.query(ProductOption)
                        .filter(ProductOption.id == item.product_option_id)
                        .first()
                    )
                    if option and option.product:
                        order_item_names.append(option.product.name)
                else:
                    option = (
                        db.query(UsedProductOption)
                        .filter(UsedProductOption.id == item.product_option_id)
                        .first()
                    )
                    if option and option.used_product:
                        order_item_names.append(option.used_product.name)
            track_order_action(
                db,
                user_id,
                order.id,
                HistoryActionType.ORDER_RE,
                user_name=user.name if user else None,
                order_item_name=", ".join(order_item_names)
                if order_item_names
                else None,
            )
        except Exception:
            pass  # 히스토리 기록 실패해도 반품 접수 결과에 영향 없음

        return {
            "success": True,
            "message": f"반품 접수가 완료되었습니다. 택배기사님이 {pickup_address}로 방문할 예정입니다.",
            "status": "refunded (return requested)",
            "reason": reason,
            "responsibility": responsibility,
            "return_shipping_fee": return_shipping_fee,
            "final_refund_amount": final_refund,
            "pickup_address": pickup_address,
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"반품 접수 실패: {str(e)}"}
    finally:
        db.close()


@tool("change_option")
def change_product_option(
    order_id: str | None = None,
    user_id: int = 1,
    new_option_id: int | None = None,
    confirmed: bool | None = None,
) -> dict:
    """
    주문 옵션을 변경합니다.

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        new_option_id: 변경할 옵션 ID

    Returns:
        변경 결과
    """
    db = SessionLocal()
    try:
        resolved_order_id, selection_payload = _resolve_order_id_or_payload(
            user_id=user_id,
            order_id=order_id,
            action_context="exchange",
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "옵션 변경할 주문을 선택해주세요.",
            }

        # 캐시 무효화 (이전 세션에서 detached된 객체 방지)
        _order_cache.pop(f"{user_id}:{resolved_order_id}", None)

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        resolved_new_option_id = _require_new_option_id(
            db=db,
            order=order,
            action_context="exchange",
            new_option_id=new_option_id,
        )
        if resolved_new_option_id is None:
            return {
                "eligible": False,
                "needs_new_option": True,
                "message": "교환 가능한 옵션을 찾을 수 없습니다.",
            }

        if order.status not in [OrderStatus.PAID, OrderStatus.PREPARING]:
            return {
                "error": "결제 완료 또는 상품준비중 상태에서만 옵션 변경이 가능합니다. 교환 신청을 이용해주세요."
            }

        validation, validation_error = _validate_exchange_option_stock(
            db, order, resolved_new_option_id
        )
        if validation_error:
            return validation_error
        assert validation is not None

        matching_items = validation["matching_items"]
        required_qty = validation["required_quantity"]
        old_option_qty_map = validation["old_option_qty_map"]
        item_type = validation["item_type"]
        new_option = validation["new_option"]

        # 이미 동일 옵션이면 변경 불필요
        if all(item.product_option_id == resolved_new_option_id for item in matching_items):
            return {
                "success": True,
                "message": "이미 선택한 옵션으로 주문되어 있습니다.",
                "status": "no_change",
                "order_id": resolved_order_id,
                "new_option_id": resolved_new_option_id,
            }

        option_size = (getattr(new_option, "size_name", None) or "FREE").strip()
        option_color = (getattr(new_option, "color", None) or "FREE").strip()

        approved = _require_human_confirmation(
            action="change_option",
            prompt=(
                "선택한 옵션으로 변경을 진행할까요? "
                f"(사이즈: {option_size}, 색상: {option_color}, 수량: {required_qty})"
            ),
            context={
                "order_id": resolved_order_id,
                "new_option_id": resolved_new_option_id,
                "size_name": option_size,
                "color": option_color,
                "required_quantity": required_qty,
                "available_quantity": validation["available_quantity"],
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "옵션 변경이 취소되었습니다.",
                "order_id": resolved_order_id,
                "new_option_id": resolved_new_option_id,
            }

        # 기존 옵션 재고 복구
        option_model = ProductOption if item_type == ProductType.NEW else UsedProductOption
        inv_type = InvProductType.NEW if item_type == ProductType.NEW else InvProductType.USED

        for old_option_id, qty in old_option_qty_map.items():
            old_option = db.query(option_model).filter(option_model.id == old_option_id).first()
            if old_option:
                old_option.quantity += qty
                db.add(
                    InventoryTransaction(
                        product_option_type=inv_type,
                        product_option_id=old_option_id,
                        quantity_change=qty,
                        transaction_type=TransactionType.RETURN,
                        reference_id=order.id,
                        notes=f"챗봇 옵션 교환(배송 전) - 기존 옵션 복구 (주문번호: {order.order_number})",
                    )
                )

        # 신규 옵션 재고 차감
        new_option.quantity -= required_qty
        db.add(
            InventoryTransaction(
                product_option_type=inv_type,
                product_option_id=resolved_new_option_id,
                quantity_change=-required_qty,
                transaction_type=TransactionType.SALE,
                reference_id=order.id,
                notes=f"챗봇 옵션 교환(배송 전) - 신규 옵션 차감 (주문번호: {order.order_number})",
            )
        )

        # 주문 아이템 옵션 변경
        for item in matching_items:
            item.product_option_id = resolved_new_option_id

        order.shipping_request = f"Option changed to {resolved_new_option_id}"
        db.commit()

        return {
            "success": True,
            "message": f"주문 옵션이 ID {resolved_new_option_id}(으)로 변경되었습니다.",
            "status": "updated",
            "order_id": resolved_order_id,
            "new_option_id": resolved_new_option_id,
            "changed_quantity": required_qty,
            "remaining_stock": int(new_option.quantity),
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"옵션 변경 실패: {str(e)}"}
    finally:
        db.close()


@tool("exchange")
def register_exchange_request(
    order_id: str | None = None,
    user_id: int = 1,
    reason: str = "교환 요청",
    pickup_address: str | None = None,
    new_option_id: int | None = None,
    confirmed: bool | None = None,
) -> dict:
    """
    교환을 접수합니다 (배송 후, 회수/재배송).

    [호출 가이드]
    - 이 도구는 실제 교환 접수(상태 변경) 단계입니다.
    - 반드시 사용자가 교환할 `new_option_id`를 선택한 이후 호출해야 합니다.
    - `new_option_id`에 대해 재고가 남아있는지(수량 > 0) 확인 후 접수해야 합니다.
    - `pickup_address`가 비어 있으면 반품/환불과 동일하게
      사용자 기본 배송지(또는 주문 배송지)를 기본값으로 사용해야 합니다.

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 교환 사유
        pickup_address: 반품 수거지 주소 (선택). 미입력 시 사용자 기본 배송지/주문 배송지를 기본값으로 사용
        new_option_id: 교환할 새로운 옵션 ID (교환 접수 전 필수 확인 권장)
        confirmed: 사용자 확인 여부. None이면 checkpoint로 승인 요청을 발생시킵니다.

    Returns:
        교환 접수 결과 (이전 상태, 현재 처리 상태, 수거지 등)
    """
    db = SessionLocal()
    try:
        if not (order_id or "").strip() and new_option_id is not None:
            return {
                "success": False,
                "error": (
                    "주문번호 없이 교환 접수를 진행할 수 없습니다. "
                    "배송 전 교환은 옵션 변경으로 완료되며, 배송 후 교환은 주문을 먼저 선택해주세요."
                ),
                "needs_order_id": True,
            }

        resolved_order_id, selection_payload = _resolve_order_id_or_payload(
            user_id=user_id,
            order_id=order_id,
            action_context="exchange",
        )
        if not resolved_order_id:
            if selection_payload:
                return selection_payload
            return {
                "success": False,
                "needs_order_id": True,
                "message": "교환할 주문을 선택해주세요.",
            }

        # 캐시 무효화 (이전 세션에서 detached된 객체 방지)
        _order_cache.pop(f"{user_id}:{resolved_order_id}", None)

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        if order.status not in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return {"error": "배송 전입니다. 옵션 변경 기능을 이용해주세요."}

        if order.status == OrderStatus.DELIVERED:
            delivered_at = order.shipping_info.delivered_at if order.shipping_info else None
            is_valid, error_msg = _check_return_period(delivered_at)
            if not is_valid:
                return {"error": error_msg}

        resolved_new_option_id = _require_new_option_id(
            db=db,
            order=order,
            action_context="exchange",
            new_option_id=new_option_id,
        )
        if resolved_new_option_id is None:
            return {
                "eligible": False,
                "needs_new_option": True,
                "message": "교환 가능한 옵션을 찾을 수 없습니다.",
            }

        validation, validation_error = _validate_exchange_option_stock(
            db, order, resolved_new_option_id
        )
        if validation_error:
            return validation_error
        assert validation is not None

        if not pickup_address:
            pickup_address = _resolve_default_pickup_address(db, user_id, order)

        shipping_fee = float(order.shipping_fee)
        exchange_fee = shipping_fee * 2

        approved = _require_human_confirmation(
            action="exchange",
            prompt=(
                "교환 접수를 진행할까요? "
                f"(왕복 배송비: {exchange_fee:,.0f}원, "
                f"요청 수량: {validation['required_quantity']}, 가용 재고: {validation['available_quantity']})"
            ),
            context={
                "order_id": resolved_order_id,
                "reason": reason,
                "new_option_id": resolved_new_option_id,
                "pickup_address": pickup_address,
                "required_quantity": validation["required_quantity"],
                "available_quantity": validation["available_quantity"],
                "exchange_fee": exchange_fee,
            },
            confirmed=confirmed,
        )

        if not approved:
            return {
                "success": False,
                "message": "교환 접수가 취소되었습니다.",
                "order_id": resolved_order_id,
            }

        # 승인 후 재검증 (동시성으로 인한 재고 변동 방지)
        revalidation, revalidation_error = _validate_exchange_option_stock(
            db, order, resolved_new_option_id
        )
        if revalidation_error:
            return revalidation_error
        assert revalidation is not None

        # 상태 변경
        previous_status = order.status
        order.status = OrderStatus.PREPARING  # 교환 처리중
        order.shipping_request = (
            f"Exchange Requested. Reason: {reason}, "
            f"Pickup: {pickup_address}, New Option: {resolved_new_option_id}"
        )
        db.commit()

        return {
            "success": True,
            "message": "교환 접수가 완료되었습니다. 수거 및 재배송이 진행됩니다.",
            "previous_status": previous_status.value,
            "current_status": "processing (exchange)",
            "pickup_address": pickup_address,
            "new_option_id": resolved_new_option_id,
            "required_quantity": revalidation["required_quantity"],
            "available_quantity": revalidation["available_quantity"],
            "exchange_fee": exchange_fee,
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"교환 접수 실패: {str(e)}"}
    finally:
        db.close()


@tool("shipping")
def get_shipping_details(order_id: str | None = None, user_id: int = 1) -> dict:
    """
    주문의 배송 현황과 택배사 정보를 통합 조회합니다.

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID

    Returns:
        배송 상태, 현재 위치, 예상 도착일, 택배사 정보(이름/전화번호) 등
    """
    db = SessionLocal()
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

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        shipping_info = order.shipping_info
        if not shipping_info:
            return {
                "status": "배송 준비 중",
                "message": "아직 배송 정보가 등록되지 않았습니다.",
            }

        # Mock contact info based on courier name
        courier = shipping_info.courier_company
        courier_phone = "Unknown"
        courier_website = "Unknown"

        if courier == "FastDelivery":
            courier_phone = "1588-0000"
            courier_website = "www.fastdelivery.com"

        return {
            "status": "배송 중"
            if order.status == OrderStatus.SHIPPED
            else order.status.value,
            "tracking_number": shipping_info.tracking_number,
            "shipped_at": shipping_info.shipped_at.strftime("%Y-%m-%d")
            if shipping_info.shipped_at
            else None,
            "courier_name": courier,
            "courier_phone": courier_phone,
            "courier_website": courier_website,
            "current_location": "대전 Hub (가상)",  # Mock Data
            "estimated_delivery": "내일 도착 예정",  # Mock Data
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"배송 정보 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool("update_payment")
def update_payment_method(
    order_id: str | None = None,
    user_id: int = 1,
    payment_method: str = "카드",
    card_number: str | None = None,
) -> dict:
    """
    주문의 결제 정보를 변경합니다.

    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        payment_method: 결제 수단 (카드/계좌이체/무통장입금)
        card_number: 카드번호 (카드 결제 시, 마스킹 처리 권장)

    Returns:
        성공 여부, 메시지, 새로운 결제 수단
    """
    db = SessionLocal()
    try:
        resolved_order_id = _require_order_id(
            user_id=user_id,
            order_id=order_id,
            action_context="update_payment",
        )
        if not resolved_order_id:
            return {
                "success": False,
                "needs_order_id": True,
                "message": "결제 정보를 수정할 주문을 선택해주세요.",
            }

        order, error = _get_order_with_auth(db, resolved_order_id, user_id)
        if error:
            return error
        assert order is not None  # Type narrowing

        order.payment_method = payment_method
        if card_number:
            order.card_number = card_number
        db.commit()

        return {
            "success": True,
            "message": "결제 정보가 업데이트되었습니다.",
            "new_payment_method": payment_method,
            "card_number_updated": card_number is not None,
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"결제 정보 수정 실패: {str(e)}"}
    finally:
        db.close()


def get_user_orders(
    user_id: int = 1,
    limit: int = 5,
    days: int = 30,
    requires_selection: bool = False,
    action_context: str | None = None,
) -> dict:
    """
    사용자의 최근 주문 목록을 조회합니다 (UI 렌더링용).

    [중요] 사용자가 특정 주문에 대해 환불/교환/취소 등을 하려는데 주문번호를 특정하지 않은 경우,
    반드시 `requires_selection=True`로설정하여 호출해야 합니다. 그래야 UI에 선택 버튼(체크박스 등)이 표시됩니다.

    Args:
        user_id: 사용자 ID
        limit: 조회할 주문 개수
        days: 조회 기간 (기본값 30일)
        requires_selection: 주문 선택 UI 표시 여부 (액션 수행 전 선택이 필요하면 True)
        action_context: 주문 선택 후 이어질 액션의 의도 (예: 'refund', 'exchange', 'cancel'). 없으면 None.

    Returns:
        주문 목록 및 각 주문별 환불/교환/취소 가능 여부 (UI 데이터)
    """
    from datetime import timedelta

    db = SessionLocal()
    try:
        # 최근 N일 이내 주문 조회
        cutoff_date = datetime.now() - timedelta(days=days)
        orders = (
            db.query(Order)
            .filter(Order.user_id == user_id)
            .filter(Order.created_at >= cutoff_date)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .all()
        )

        ui_data = []
        for order in orders:
            # 가능한 액션 판단
            order_actions = _get_order_actions(order)

            # 필터링 로직 추가
            if action_context == "refund" and not order_actions.get("can_return"):
                continue
            if action_context == "cancel" and not order_actions.get("can_cancel"):
                continue
            if action_context == "exchange" and not order_actions.get("can_exchange"):
                continue
            if action_context == "review" and order.status != OrderStatus.DELIVERED:
                continue

            # Get main product name
            product_name = "상품 정보 없음"
            if order.items:
                first_item = order.items[0]
                product_name = (
                    f"상품 {first_item.product_option_id} 등 {len(order.items)}건"
                )

            ui_data.append(
                {
                    "order_id": order.order_number,
                    "date": order.created_at.strftime("%Y-%m-%d"),
                    "status": order.status.value,
                    "status_label": order.status.label,  # 한글 상태명 추가
                    "product_name": product_name,
                    "amount": float(order.total_amount),
                    "delivered_at": order.shipping_info.delivered_at.strftime(
                        "%Y-%m-%d"
                    )
                    if order.shipping_info and order.shipping_info.delivered_at
                    else None,
                    **order_actions,  # 환불/교환/취소 가능 여부 포함
                }
            )

        # Context-aware message
        base_msg = f"최근 {days}일 이내 주문 내역입니다."
        if not ui_data:
            if action_context == "refund":
                msg_suffix = " (환불 가능한 주문이 없습니다.)"
            elif action_context == "exchange":
                msg_suffix = " (교환 가능한 주문이 없습니다.)"
            elif action_context == "cancel":
                msg_suffix = " (취소 가능한 주문이 없습니다.)"
            elif action_context == "review":
                msg_suffix = " (리뷰 작성이 가능한 배송완료 주문이 없습니다.)"
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

        if action_context == "refund":
            msg_suffix = " 환불하실 주문을 선택해주세요."
        elif action_context == "exchange":
            msg_suffix = " 교환하실 주문을 선택해주세요."
        elif action_context == "cancel":
            msg_suffix = " 취소하실 주문을 선택해주세요."
        elif action_context == "review":
            msg_suffix = " 리뷰를 작성하실 주문을 선택해주세요."
        else:
            msg_suffix = ""

        return {
            "ui_action": "show_order_list",
            "message": base_msg + msg_suffix,
            "total_orders": len(ui_data),
            "ui_data": ui_data,
            # action_context 없는 단순 조회 → 선택 불필요, 강제 False
            "requires_selection": requires_selection and action_context is not None,
            "prior_action": action_context,
        }
    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        return {"error": f"주문 목록 조회 실패: {str(e)}"}
    finally:
        db.close()
