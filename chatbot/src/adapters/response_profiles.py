from __future__ import annotations

from typing import Any

from chatbot.src.onboarding_v2.models.planning import ResolvedResponseContract

from .schema import DeliveryStatus, GetDeliveryTrackingResult, GetOrderStatusResult, OrderStatus
from .site_a.mappers import (
    map_site_a_delivery,
    map_site_a_order,
    map_site_a_product_search,
    map_site_a_user,
)
from .site_b.mappers import (
    map_site_b_delivery,
    map_site_b_order,
    map_site_b_product_search,
    map_site_b_user,
    to_delivery_status_token,
    to_order_status_token,
)
from .site_c.mappers import (
    map_site_c_delivery,
    map_site_c_order,
    map_site_c_product_search,
    map_site_c_user,
)


def map_user_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
    site_id: str,
):
    if contract.user_profile == "orders_collection_user_id":
        return map_site_b_user(raw, site_id)
    if contract.user_profile == "direct_user_session":
        return map_site_c_user(raw, site_id)
    return map_site_a_user(raw, site_id)


def map_product_search_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
    site_id: str,
):
    if contract.product_profile == "products_wrapper_collection":
        return map_site_b_product_search(raw, site_id)
    if contract.product_profile == "catalog_items_keyword_results":
        return map_site_c_product_search(raw, site_id)
    return map_site_a_product_search(raw, site_id)


def map_order_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
    deps: dict[str, Any],
) -> GetOrderStatusResult:
    if contract.order_profile == "orders_collection_scan":
        return map_site_b_order(raw, deps)
    if contract.order_profile == "user_scoped_order_service":
        return map_site_c_order(raw, deps)
    return map_site_a_order(raw, deps)


def map_delivery_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
    deps: dict[str, Any],
) -> GetDeliveryTrackingResult:
    if contract.delivery_profile == "orders_collection_scan":
        return map_site_b_delivery(raw, deps)
    if contract.delivery_profile == "shipping_tracking_record":
        return map_site_c_delivery(raw, deps)
    return map_site_a_delivery(raw, deps)


def normalize_order_status_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
) -> OrderStatus:
    token = _normalize_order_token(contract.order_status_profile, raw)
    return {
        "pending": OrderStatus.PENDING,
        "created": OrderStatus.PENDING,
        "paid": OrderStatus.PAID,
        "payment_complete": OrderStatus.PAID,
        "preparing": OrderStatus.PREPARING,
        "packing": OrderStatus.PREPARING,
        "shipped": OrderStatus.SHIPPED,
        "shipping": OrderStatus.SHIPPED,
        "delivered": OrderStatus.DELIVERED,
        "done": OrderStatus.DELIVERED,
        "cancel_requested": OrderStatus.CANCEL_REQUESTED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "exchange_requested": OrderStatus.EXCHANGE_REQUESTED,
        "refund_requested": OrderStatus.REFUND_REQUESTED,
        "refunded": OrderStatus.REFUNDED,
    }.get(token, OrderStatus.UNKNOWN)


def normalize_delivery_status_from_contract(
    contract: ResolvedResponseContract,
    raw: Any,
) -> DeliveryStatus:
    token = _normalize_delivery_token(contract.delivery_status_profile, raw)
    return {
        "ready": DeliveryStatus.READY,
        "in_transit": DeliveryStatus.IN_TRANSIT,
        "shipping": DeliveryStatus.IN_TRANSIT,
        "out_for_delivery": DeliveryStatus.OUT_FOR_DELIVERY,
        "delivered": DeliveryStatus.DELIVERED,
        "delayed": DeliveryStatus.DELAYED,
    }.get(token, DeliveryStatus.UNKNOWN)


def resolve_visible_order_id_from_contract(
    contract: ResolvedResponseContract,
    raw_order: dict[str, Any],
) -> str | None:
    if contract.order_identifier_mode == "order_number_with_internal_resolution":
        for key in ("order_number", "orderNumber"):
            value = raw_order.get(key)
            if value not in (None, ""):
                return str(value)
    for key in ("order_id", "orderId", "id"):
        value = raw_order.get(key)
        if value not in (None, ""):
            return str(value)
    nested_order = raw_order.get("order")
    if isinstance(nested_order, dict):
        return resolve_visible_order_id_from_contract(contract, nested_order)
    return None


def _normalize_order_token(profile: str, raw: Any) -> str:
    value = str(raw or "unknown").strip()
    if profile == "korean_labels":
        return to_order_status_token(value)
    return value.lower()


def _normalize_delivery_token(profile: str, raw: Any) -> str:
    value = str(raw or "unknown").strip()
    if profile == "korean_labels":
        return to_delivery_status_token(value)
    return value.lower()
