"""
Integration tests for all three Python site adapters (site_a, site_b, site_c).
These tests mock httpx calls to verify that:
  1. Each adapter correctly maps raw API responses into the common Pydantic schema.
  2. Auth headers are built correctly.
  3. The AdapterRegistry routes correctly by site_id.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from chatbot.src.adapters.schema import (
    AuthenticatedContext, ProductSearchFilter, GetOrderStatusInput,
    GetDeliveryTrackingInput, SubmitOrderActionInput, OrderActionType, OrderActionReason,
    OrderStatus, DeliveryStatus, KnowledgeSearchInput
)
from chatbot.src.adapters.site_a.client import SiteAClient
from chatbot.src.adapters.site_a.adapter import SiteAAdapter
from chatbot.src.adapters.site_b.client import SiteBClient
from chatbot.src.adapters.site_b.adapter import SiteBAdapter
from chatbot.src.adapters.site_c.client import SiteCClient
from chatbot.src.adapters.site_c.adapter import SiteCAdapter
from chatbot.src.adapters.base import AdapterRegistry
from chatbot.src.adapters.schema import AdapterError


def run(coro):
    """Synchronously run a coroutine."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_ctx(site_id: str, user_id: str = "42", access_token: str = "tok_test") -> AuthenticatedContext:
    return AuthenticatedContext(siteId=site_id, userId=user_id, accessToken=access_token)


# ═══════════════════════════════════════════════════════════════════════════════
# Site A (Food Backend) Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSiteAAdapter:

    def _make_adapter(self) -> SiteAAdapter:
        client = SiteAClient(base_url="http://mock-food:8002")
        return SiteAAdapter(client=client)

    def test_healthcheck_returns_ok(self):
        adapter = self._make_adapter()
        result = run(adapter.healthcheck())
        assert result.ok is True
        assert result.siteId == "site-a"

    def test_search_products_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-a")

        raw = [
            {"id": 1, "name": "파스타", "description": "맛있는", "price": "12000",
             "stock": 5, "image": "http://img.com/1.jpg", "category": 3}
        ]
        adapter.client.search_products = AsyncMock(return_value=raw)

        result = run(adapter.search_products(ctx, ProductSearchFilter(query="파스타")))

        assert len(result.items) == 1
        assert result.items[0].id == "1"
        assert result.items[0].title == "파스타"
        assert result.items[0].price is not None
        assert result.items[0].price.amount == 12000.0
        assert result.items[0].inStock is True

    def test_get_order_status_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-a")

        raw = {
            "id": "ORD-001", "status": "delivered", "quantity": 2, "total_price": "24000",
            "created_at": "2024-01-01",
            "product": {"id": "P1", "name": "파스타", "price": "12000", "image_url": "http://img.com/1.jpg"}
        }
        adapter.client.get_order = AsyncMock(return_value=raw)

        result = run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId="ORD-001")))

        assert result.order.orderId == "ORD-001"
        assert result.order.status == OrderStatus.DELIVERED
        assert result.order.items[0].productTitle == "파스타"
        assert result.order.items[0].quantity == 2

    def test_search_knowledge_raises_not_supported(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-a")

        with pytest.raises(AdapterError) as exc_info:
            run(adapter.search_knowledge(ctx, KnowledgeSearchInput(query="배송 정책")))
        assert exc_info.value.code == "NOT_SUPPORTED"

    def test_submit_order_action_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-a")

        # Mock order lookup (authorization)
        order_mock = MagicMock()
        adapter.get_order_status = AsyncMock(return_value=order_mock)
        adapter.client.submit_order_action = AsyncMock(return_value={"message": "취소 완료"})

        result = run(adapter.submit_order_action(ctx, SubmitOrderActionInput(
            orderId="ORD-001", actionType=OrderActionType.CANCEL, reasonCode=OrderActionReason.CHANGED_MIND
        )))

        assert result.success is True
        assert result.status.value == "accepted"


# ═══════════════════════════════════════════════════════════════════════════════
# Site B (Bilyeo Backend) Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSiteBAdapter:

    def _make_adapter(self) -> SiteBAdapter:
        client = SiteBClient(base_url="http://mock-bilyeo:5000")
        return SiteBAdapter(client=client)

    def test_healthcheck_returns_ok(self):
        adapter = self._make_adapter()
        result = run(adapter.healthcheck())
        assert result.ok is True
        assert result.siteId == "site-b"

    def test_search_products_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-b")

        raw = {
            "products": [
                {"product_id": 10, "name": "비료상품", "price": "5000", "stock": 20,
                 "image_url": "http://img.com/2.jpg", "category": "농업"}
            ]
        }
        adapter.client.search_products = AsyncMock(return_value=raw)

        result = run(adapter.search_products(ctx, ProductSearchFilter(query="비료")))

        assert len(result.items) == 1
        assert result.items[0].id == "10"
        assert result.items[0].title == "비료상품"
        assert result.items[0].inStock is True

    def test_get_order_status_finds_correct_order(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-b", user_id="7")

        raw = {
            "orders": [
                {
                    "order_id": "99", "user_id": "7", "status": "배송완료", "total_price": "15000",
                    "created_at": "2024-02-01",
                    "items": [{"product_id": "10", "product_name": "비료", "quantity": 3, "price": "5000", "image_url": None}]
                },
                {"order_id": "100", "user_id": "7", "status": "결제완료", "items": []}
            ]
        }
        adapter.client.get_order = AsyncMock(return_value=raw)

        result = run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId="99")))

        assert result.order.orderId == "99"
        assert result.order.status == OrderStatus.DELIVERED
        assert len(result.order.items) == 1

    def test_submit_order_action_raises_not_supported(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-b")

        with pytest.raises(AdapterError) as exc_info:
            run(adapter.submit_order_action(ctx, SubmitOrderActionInput(
                orderId="99", actionType=OrderActionType.CANCEL, reasonCode=OrderActionReason.CHANGED_MIND
            )))
        assert exc_info.value.code == "NOT_SUPPORTED"


# ═══════════════════════════════════════════════════════════════════════════════
# Site C (Ecommerce Backend) Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSiteCAdapter:

    def _make_adapter(self) -> SiteCAdapter:
        client = SiteCClient(base_url="http://mock-ecommerce:8000")
        return SiteCAdapter(client=client)

    def test_healthcheck_returns_ok(self):
        adapter = self._make_adapter()
        result = run(adapter.healthcheck())
        assert result.ok is True
        assert result.siteId == "site-c"

    def test_validate_auth_matches_user_id(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-c", user_id="5")

        raw = {"id": "5", "email": "test@test.com", "name": "홍길동", "authenticated": True}
        adapter.client.validate_session = AsyncMock(return_value=raw)

        result = run(adapter.validate_auth(ctx))
        assert result.id == "5"
        assert result.email == "test@test.com"

    def test_search_products_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-c")

        raw = [{"id": 30, "name": "청바지", "description": "슬림 핏", "price": "49000", "inStock": True, "category_id": 5}]
        adapter.client.search_products = AsyncMock(return_value=raw)

        result = run(adapter.search_products(ctx, ProductSearchFilter(query="청바지")))

        assert len(result.items) == 1
        assert result.items[0].id == "30"
        assert result.items[0].price.amount == 49000.0

    def test_get_order_status_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-c", user_id="5")

        raw = {
            "id": "ORD-999", "user_id": "5", "status": "SHIPPED", "total_amount": "49000",
            "created_at": "2024-03-01",
            "items": [{"product_id": "30", "product_name": "청바지", "quantity": 1, "unit_price": "49000"}]
        }
        adapter.client.get_order = AsyncMock(return_value=raw)

        result = run(adapter.get_order_status(ctx, GetOrderStatusInput(orderId="ORD-999")))

        assert result.order.orderId == "ORD-999"
        assert result.order.status == OrderStatus.SHIPPED
        assert result.order.items[0].productTitle == "청바지"

    def test_delivery_tracking_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-c", user_id="5")

        order_mock = MagicMock()
        order_mock.order.userId = "5"
        adapter.get_order_status = AsyncMock(return_value=order_mock)

        raw = {
            "order_id": "ORD-999", "courier_company": "CJ대한통운", "tracking_number": "1234567890",
            "shipped_at": "2024-03-01", "delivered_at": None, "updated_at": "2024-03-02"
        }
        adapter.client.get_delivery = AsyncMock(return_value=raw)

        result = run(adapter.get_delivery_tracking(ctx, GetDeliveryTrackingInput(orderId="ORD-999")))

        assert result.tracking.orderId == "ORD-999"
        assert result.tracking.deliveryStatus == DeliveryStatus.IN_TRANSIT
        assert result.tracking.carrierName == "CJ대한통운"

    def test_cancel_order_action_maps_correctly(self):
        adapter = self._make_adapter()
        ctx = make_ctx(site_id="site-c", user_id="5")

        order_mock = MagicMock()
        order_mock.order.userId = "5"
        adapter.get_order_status = AsyncMock(return_value=order_mock)
        adapter.client.submit_cancel = AsyncMock(return_value={"message": "주문이 취소되었습니다."})

        result = run(adapter.submit_order_action(ctx, SubmitOrderActionInput(
            orderId="ORD-999", actionType=OrderActionType.CANCEL,
            reasonCode=OrderActionReason.CHANGED_MIND, reasonText="단순 변심"
        )))

        assert result.success is True
        assert result.status.value == "requested"


# ═══════════════════════════════════════════════════════════════════════════════
# AdapterRegistry Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterRegistry:

    def setup_method(self):
        AdapterRegistry._adapters.clear()

    def test_register_and_get_adapter(self):
        adapter = SiteCAdapter(client=SiteCClient(base_url="http://ecommerce"))
        AdapterRegistry.register(adapter)

        retrieved = AdapterRegistry.get("site-c")
        assert retrieved.site_id == "site-c"

    def test_get_unknown_site_id_raises_error(self):
        with pytest.raises(AdapterError) as exc_info:
            AdapterRegistry.get("site-unknown")
        assert exc_info.value.code == "NOT_FOUND"

    def test_list_site_ids(self):
        AdapterRegistry.register(SiteAAdapter(client=SiteAClient(base_url="http://food")))
        AdapterRegistry.register(SiteBAdapter(client=SiteBClient(base_url="http://bilyeo")))

        ids = AdapterRegistry.list_site_ids()
        assert "site-a" in ids  # SiteAAdapter (Food)
        assert "site-b" in ids  # SiteBAdapter (Bilyeo)
