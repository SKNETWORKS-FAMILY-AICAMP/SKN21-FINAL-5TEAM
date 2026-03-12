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


def map_site_c_user(raw: Any, site_id: str) -> User:
    if raw.get("authenticated") is False:
        return User(id="", siteId=site_id)

    return User(
        id=str(raw.get("id", "")),
        siteId=site_id,
        email=raw.get("email"),
        name=raw.get("name"),
    )


def map_site_c_product_search(raw: Any, site_id: str) -> ProductSearchResult:
    raw_list = raw if isinstance(raw, list) else []
    items: List[ProductSummary] = []

    for item in raw_list:
        price_obj = None
        if item.get("price") is not None:
            price_obj = Money(
                amount=float(item.get("price")), currency=item.get("currency", "KRW")
            )

        items.append(
            ProductSummary(
                id=str(item.get("id")),
                siteId=site_id,
                title=item.get("name", ""),
                shortDescription=item.get("description"),
                price=price_obj,
                inStock=item.get("inStock"),
                imageUrl=None,
                categoryIds=[str(item.get("category_id"))]
                if item.get("category_id")
                else None,
                brand=None,
            )
        )

    return ProductSearchResult(items=items, total=len(items))


def map_site_c_order(raw: Any, deps: Dict[str, Any]) -> GetOrderStatusResult:
    site_id = deps["site_id"]
    norm_order_status = deps["normalize_order_status"]

    items = []
    for item in raw.get("items", []):
        unit_price = (
            Money(amount=float(item.get("unit_price")), currency="KRW")
            if item.get("unit_price") is not None
            else None
        )

        product_id = item.get("product_id")
        if product_id is None:
            product_id = item.get("id", "")

        items.append(
            OrderItem(
                productId=str(product_id),
                productTitle=item.get("product_name", ""),
                quantity=int(item.get("quantity", 0)),
                unitPrice=unit_price,
                imageUrl=None,
            )
        )

    total_amount = (
        Money(amount=float(raw.get("total_amount")), currency="KRW")
        if raw.get("total_amount") is not None
        else None
    )

    order = OrderSummary(
        orderId=str(raw.get("id")),
        siteId=site_id,
        userId=str(raw.get("user_id")),
        status=norm_order_status(str(raw.get("status", "unknown"))),
        items=items,
        totalPrice=total_amount,
        orderedAt=raw.get("created_at"),
    )
    return GetOrderStatusResult(order=order)


def map_site_c_delivery(raw: Any, deps: Dict[str, Any]) -> GetDeliveryTrackingResult:
    delivery_raw_status = "ready"
    if raw.get("delivered_at"):
        delivery_raw_status = "delivered"
    elif raw.get("shipped_at"):
        delivery_raw_status = "in_transit"

    tracking = DeliveryTracking(
        orderId=str(raw.get("order_id")),
        deliveryStatus=deps["normalize_delivery_status"](delivery_raw_status),
        carrierName=raw.get("courier_company"),
        trackingNumber=raw.get("tracking_number"),
        lastUpdatedAt=raw.get("updated_at"),
    )
    return GetDeliveryTrackingResult(tracking=tracking)


def map_site_c_order_action(raw: Any) -> SubmitOrderActionResult:
    return SubmitOrderActionResult(
        success=bool(raw.get("message")),
        status="requested",
        message=raw.get("message", "요청이 접수되었습니다."),
    )
