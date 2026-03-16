import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.tools import order_tools
from ecommerce.backend.app.router.orders.schemas import OrderStatus


class DummyDB:
    def rollback(self):
        return None

    def close(self):
        return None


def test_exchange_delegates_to_change_option_for_pre_shipment_order(monkeypatch):
    delegated_payloads: list[dict] = []

    monkeypatch.setattr(order_tools, "SessionLocal", lambda: DummyDB())
    monkeypatch.setattr(
        order_tools,
        "_resolve_order_id_or_payload",
        lambda **kwargs: ("ORD-20260303-0001", None),
    )
    monkeypatch.setattr(
        order_tools,
        "_get_order_with_auth",
        lambda db, order_id, user_id: (
            SimpleNamespace(status=OrderStatus.PAID, shipping_info=None),
            None,
        ),
    )

    def fake_change_option_invoke(payload: dict):
        delegated_payloads.append(payload)
        return {
            "ui_action": "show_option_list",
            "message": "옵션을 선택해주세요.",
            "order_id": payload["order_id"],
            "requires_selection": True,
            "prior_action": "exchange",
            "ui_data": [],
        }

    monkeypatch.setattr(
        order_tools,
        "change_product_option",
        SimpleNamespace(invoke=fake_change_option_invoke),
    )

    result = order_tools.register_exchange_request.invoke(
        {
            "order_id": "ORD-20260303-0001",
            "user_id": 1,
            "reason": "사이즈 교환",
        }
    )

    assert result["ui_action"] == "show_option_list"
    assert delegated_payloads == [
        {
            "order_id": "ORD-20260303-0001",
            "user_id": 1,
            "new_option_id": None,
            "confirmed": None,
        }
    ]
