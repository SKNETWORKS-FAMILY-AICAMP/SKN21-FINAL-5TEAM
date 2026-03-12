from typing import Any, Dict, List
from ..schema import (
    User,
    ProductSearchResult,
    ProductSummary,
    Money,
    GetOrderStatusResult,
    OrderSummary,
    OrderItem,
    GetDeliveryTrackingResult,
    DeliveryTracking,
    SubmitOrderActionResult,
)


def to_order_status_token(raw: Any) -> str:
    val = str(raw or "unknown").lower()
    if "결제" in val and "대기" in val:
        return "pending"
    if "결제" in val and "완료" in val:
        return "paid"
    if "배송" in val and "준비" in val:
        return "preparing"
    if "배송" in val and "중" in val:
        return "shipped"
    if "배송" in val and "완료" in val:
        return "delivered"
    if "취소" in val:
        return "cancelled"
    if "환불" in val:
        return "refunded"
    return val


def to_delivery_status_token(raw: Any) -> str:
    val = str(raw or "unknown").lower()
    if "준비" in val:
        return "ready"
    if "배송" in val and "중" in val:
        return "in_transit"
    if "완료" in val:
        return "delivered"
    return val


def map_site_b_user(raw: Any, site_id: str) -> User:
    orders = raw.get("orders", [])
    user_id = str(orders[0].get("user_id", "")) if orders else ""
    return User(id=user_id, siteId=site_id, email=None, name=None)


def map_site_b_product_search(raw: Any, site_id: str) -> ProductSearchResult:
    products = raw.get("products", [])
    items: List[ProductSummary] = []

    for item in products:
        price_obj = None
        if item.get("price") is not None:
            price_obj = Money(amount=float(item.get("price")), currency="KRW")

        items.append(
            ProductSummary(
                id=str(item.get("product_id")),
                siteId=site_id,
                title=item.get("name", ""),
                shortDescription=item.get("description"),
                price=price_obj,
                inStock=(item.get("stock", 0) > 0),
                imageUrl=item.get("image_url"),
                categoryIds=[str(item.get("category"))]
                if item.get("category")
                else None,
                brand=item.get("brand"),
            )
        )

    return ProductSearchResult(items=items, total=len(items))


def map_site_b_order(raw: Any, deps: Dict[str, Any]) -> GetOrderStatusResult:
    site_id = deps["site_id"]
    current_user_id = deps["current_user_id"]
    target_order_id = deps["target_order_id"]
    norm_order_status = deps["normalize_order_status"]

    orders = raw.get("orders", [])
    found_order = next(
        (o for o in orders if str(o.get("order_id")) == target_order_id),
        orders[0] if orders else {},
    )
    order_id = found_order.get("order_id", "")

    items = []
    for item in found_order.get("items", []):
        unit_price = (
            Money(amount=float(item.get("price")), currency="KRW")
            if item.get("price") is not None
            else None
        )
        items.append(
            OrderItem(
                productId=str(item.get("product_id")),
                productTitle=item.get("product_name", ""),
                quantity=int(item.get("quantity", 0)),
                unitPrice=unit_price,
                imageUrl=item.get("image_url"),
            )
        )

    total_price = (
        Money(amount=float(found_order.get("total_price")), currency="KRW")
        if found_order.get("total_price") is not None
        else None
    )

    order = OrderSummary(
        orderId=str(order_id),
        siteId=site_id,
        userId=current_user_id,
        status=norm_order_status(
            to_order_status_token(found_order.get("status", "unknown"))
        ),
        items=items,
        totalPrice=total_price,
        orderedAt=found_order.get("created_at"),
    )
    return GetOrderStatusResult(order=order)


def map_site_b_delivery(raw: Any, deps: Dict[str, Any]) -> GetDeliveryTrackingResult:
    target_order_id = deps["target_order_id"]
    orders = raw.get("orders", [])
    found_order = next(
        (o for o in orders if str(o.get("order_id")) == target_order_id),
        orders[0] if orders else {},
    )
    order_id = str(found_order.get("order_id", ""))

    tracking = DeliveryTracking(
        orderId=order_id,
        deliveryStatus=deps["normalize_delivery_status"](
            to_delivery_status_token(found_order.get("status", "unknown"))
        ),
        lastUpdatedAt=found_order.get("created_at"),
    )
    return GetDeliveryTrackingResult(tracking=tracking)


def map_site_b_order_action(raw: Any) -> SubmitOrderActionResult:
    return SubmitOrderActionResult(
        success=False,
        status="not_allowed",
        message="bilyeo 사이트는 주문 액션 API를 제공하지 않습니다.",
    )
