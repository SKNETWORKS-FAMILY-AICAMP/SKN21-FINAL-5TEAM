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


def map_site_a_user(raw: Any, site_id: str) -> User:
    user_data = raw.get("user", {})
    return User(
        id=str(user_data.get("id", "")),
        siteId=site_id,
        email=user_data.get("email"),
        name=user_data.get("name"),
    )


def map_site_a_product_search(raw: Any, site_id: str) -> ProductSearchResult:
    raw_list = raw if isinstance(raw, list) else []
    items: List[ProductSummary] = []

    for item in raw_list:
        price_obj = None
        if item.get("price") is not None:
            price_obj = Money(amount=float(item.get("price")), currency="KRW")

        items.append(
            ProductSummary(
                id=str(item.get("id")),
                siteId=site_id,
                title=item.get("name", ""),
                shortDescription=item.get("description"),
                price=price_obj,
                inStock=(item.get("stock", 0) > 0),
                imageUrl=item.get("image"),
                categoryIds=[str(item.get("category"))]
                if item.get("category")
                else None,
                brand=item.get("brand"),
            )
        )

    return ProductSearchResult(items=items, total=len(items))


def map_site_a_order(raw: Any, deps: Dict[str, Any]) -> GetOrderStatusResult:
    site_id = deps["site_id"]
    user_id = deps["current_user_id"]
    norm_order_status = deps["normalize_order_status"]

    product_data = raw.get("product", {})
    unit_price = (
        Money(amount=float(product_data.get("price")), currency="KRW")
        if product_data.get("price") is not None
        else None
    )
    total_price = (
        Money(amount=float(raw.get("total_price")), currency="KRW")
        if raw.get("total_price") is not None
        else None
    )

    item = OrderItem(
        productId=str(product_data.get("id")),
        productTitle=product_data.get("name", ""),
        quantity=int(raw.get("quantity", 0)),
        unitPrice=unit_price,
        imageUrl=product_data.get("image_url"),
    )

    order = OrderSummary(
        orderId=str(raw.get("id")),
        siteId=site_id,
        userId=user_id,
        status=norm_order_status(raw.get("status", "unknown")),
        items=[item],
        totalPrice=total_price,
        orderedAt=raw.get("created_at"),
    )
    return GetOrderStatusResult(order=order)


def map_site_a_delivery(raw: Any, deps: Dict[str, Any]) -> GetDeliveryTrackingResult:
    raw_status = str(raw.get("status", "unknown")).lower()
    delivery_token = "in_transit" if raw_status == "shipping" else raw_status

    tracking = DeliveryTracking(
        orderId=str(raw.get("id")),
        deliveryStatus=deps["normalize_delivery_status"](delivery_token),
        lastUpdatedAt=raw.get("created_at"),
    )
    return GetDeliveryTrackingResult(tracking=tracking)


def map_site_a_order_action(raw: Any) -> SubmitOrderActionResult:
    ok = bool(raw.get("order") or raw.get("message"))
    return SubmitOrderActionResult(
        success=ok,
        status="accepted" if ok else "rejected",
        message=raw.get("message", "요청이 처리되었습니다."),
    )
