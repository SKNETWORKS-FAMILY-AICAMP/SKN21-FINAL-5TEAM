import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.tools import adapter_order_tools


class FakeFoodClient:
    def __init__(self, orders):
        self._orders = orders

    async def list_orders(self, headers):
        assert headers["Cookie"] == "session_token=food-token"
        return self._orders


class FakeFoodAdapter:
    site_id = "site-a"

    def __init__(self, orders=None):
        self.client = FakeFoodClient(orders or [])

    def _normalize_order_status(self, raw: str):
        mapping = {
            "preparing": "preparing",
            "shipping": "shipped",
            "delivered": "delivered",
            "exchange_requested": "exchange_requested",
        }
        return SimpleNamespace(value=mapping.get(raw, "unknown"))


def _build_adapter_with_order_status(status_value: str):
    adapter = FakeFoodAdapter()

    async def fake_get_order_status(ctx, input_data):
        return SimpleNamespace(
            order=SimpleNamespace(
                status=SimpleNamespace(value=status_value),
                totalPrice=SimpleNamespace(amount=15000),
                orderId=input_data.orderId,
                userId="1",
                items=[
                    SimpleNamespace(
                        productId="101",
                        productTitle="짜장면",
                        quantity=1,
                        unitPrice=SimpleNamespace(amount=15000),
                    )
                ],
                orderedAt="2026-03-18T10:00:00",
            )
        )

    adapter.get_order_status = fake_get_order_status
    return adapter


def test_get_user_orders_for_site_filters_exchange_candidates(monkeypatch):
    adapter = FakeFoodAdapter(
        [
            {
                "id": 11,
                "status": "delivered",
                "payment_status": "paid",
                "created_at": "2026-03-18T10:00:00",
                "total_price": "15000.00",
                "product": {"name": "짬뽕"},
            },
            {
                "id": 12,
                "status": "preparing",
                "payment_status": "paid",
                "created_at": "2026-03-18T11:00:00",
                "total_price": "9000.00",
                "product": {"name": "볶음밥"},
            },
        ]
    )
    monkeypatch.setattr(adapter_order_tools, "_get_site_adapter", lambda site_id: adapter)

    payload = adapter_order_tools.get_user_orders_for_site(
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        requires_selection=True,
        action_context="exchange",
    )

    assert payload["total_orders"] == 1
    assert payload["ui_data"][0]["order_id"] == "11"
    assert payload["ui_data"][0]["can_exchange"] is True


def test_exchange_via_adapter_returns_exchange_requested(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")

    async def fake_submit_order_action(ctx, input_data):
        assert input_data.actionType.value == "exchange"
        return SimpleNamespace(success=True, message="교환이 접수되었습니다.")

    adapter.submit_order_action = fake_submit_order_action

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_resolve_order_with_confirmation_for_site",
        lambda **kwargs: ("15", True, None),
    )

    result = adapter_order_tools.register_exchange_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "15",
            "confirmed": True,
        }
    )

    assert result["success"] is True
    assert result["status"] == "exchange_requested"


def test_cancel_via_adapter_returns_cancelled(monkeypatch):
    adapter = _build_adapter_with_order_status("preparing")

    async def fake_submit_order_action(ctx, input_data):
        assert input_data.actionType.value == "cancel"
        return SimpleNamespace(success=True, message="주문이 취소되었습니다.")

    adapter.submit_order_action = fake_submit_order_action

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_resolve_order_id_or_payload_for_site",
        lambda **kwargs: ("21", None),
    )

    result = adapter_order_tools.cancel_order_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "21",
            "confirmed": True,
        }
    )

    assert result["success"] is True
    assert result["status"] == "cancelled"


def test_refund_via_adapter_returns_refund_requested(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")

    async def fake_submit_order_action(ctx, input_data):
        assert input_data.actionType.value == "refund"
        return SimpleNamespace(success=True, message="환불이 접수되었습니다.")

    adapter.submit_order_action = fake_submit_order_action

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_resolve_order_with_confirmation_for_site",
        lambda **kwargs: ("31", True, None),
    )

    result = adapter_order_tools.register_return_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "31",
            "confirmed": True,
        }
    )

    assert result["success"] is True
    assert result["status"] == "refund_requested"


def test_get_order_status_via_adapter_returns_order_payload(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )

    result = adapter_order_tools.get_order_status_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "41",
        }
    )

    assert result["order_id"] == "41"
    assert result["status"] == "delivered"
    assert result["items"][0]["product_name"] == "짜장면"
