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
    raw_order = raw.get("order", raw) if isinstance(raw, dict) else {}

    items_data = raw_order.get("items") or []
    first_item = items_data[0] if isinstance(items_data, list) and items_data else {}
    product_data = raw_order.get("product", {})
    if not product_data and isinstance(first_item, dict):
        product_data = {
            "id": first_item.get("product_id") or first_item.get("productId"),
            "name": first_item.get("product_name") or first_item.get("productTitle"),
            "price": first_item.get("price"),
            "image_url": first_item.get("image_url"),
        }
    unit_price = (
        Money(amount=float(product_data.get("price")), currency="KRW")
        if product_data.get("price") is not None
        else None
    )
    total_price = (
        Money(amount=float(raw_order.get("total_price")), currency="KRW")
        if raw_order.get("total_price") is not None
        else None
    )
    order_items: List[OrderItem] = []
    if isinstance(items_data, list) and items_data:
        for raw_item in items_data:
            if not isinstance(raw_item, dict):
                continue
            raw_item_price = raw_item.get("price")
            raw_item_unit_price = (
                Money(amount=float(raw_item_price), currency="KRW")
                if raw_item_price is not None
                else None
            )
            order_items.append(
                OrderItem(
                    productId=str(
                        raw_item.get("product_id")
                        or raw_item.get("productId")
                        or ""
                    ),
                    productTitle=raw_item.get("product_name")
                    or raw_item.get("productTitle", ""),
                    quantity=int(raw_item.get("quantity", 0) or 0),
                    unitPrice=raw_item_unit_price,
                    imageUrl=raw_item.get("image_url") or raw_item.get("imageUrl"),
                )
            )
    if not order_items:
        order_items.append(
            OrderItem(
                productId=str(product_data.get("id") or ""),
                productTitle=product_data.get("name", ""),
                quantity=int(raw_order.get("quantity", 0) or 0),
                unitPrice=unit_price,
                imageUrl=product_data.get("image_url"),
            )
        )

    order = OrderSummary(
        orderId=str(raw_order.get("id") or raw_order.get("order_id") or ""),
        siteId=site_id,
        userId=str(raw_order.get("user_id") or user_id),
        status=norm_order_status(raw_order.get("status", "unknown")),
        items=order_items,
        totalPrice=total_price,
        orderedAt=raw_order.get("created_at"),
    )
    return GetOrderStatusResult(order=order)


def map_site_a_delivery(raw: Any, deps: Dict[str, Any]) -> GetDeliveryTrackingResult:
    raw_order = raw.get("order", raw) if isinstance(raw, dict) else {}
    shipping = raw_order.get("shipping") or {}
    raw_status = str(shipping.get("status") or raw_order.get("status") or "unknown").lower()
    delivery_token = "in_transit" if raw_status == "shipping" else raw_status

    tracking = DeliveryTracking(
        orderId=str(raw_order.get("id") or raw_order.get("order_id") or ""),
        deliveryStatus=deps["normalize_delivery_status"](delivery_token),
        lastUpdatedAt=shipping.get("delivered_at")
        or shipping.get("shipped_at")
        or raw_order.get("created_at"),
    )
    return GetDeliveryTrackingResult(tracking=tracking)


def map_site_a_order_action(raw: Any) -> SubmitOrderActionResult:
    ok = bool(raw.get("order") or raw.get("message"))
    return SubmitOrderActionResult(
        success=ok,
        status="accepted" if ok else "rejected",
        message=raw.get("message", "요청이 처리되었습니다."),
    )
