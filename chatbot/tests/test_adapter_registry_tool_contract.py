from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.adapters import setup
from chatbot.src.tools import adapter_order_tools, order_tools


def test_order_tool_registry_normalizes_list_contract_across_sites(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        adapter_order_tools,
        "get_user_orders_for_site",
        lambda **kwargs: {
            "ui_action": "show_order_list",
            "message": f'{kwargs["site_id"]} orders',
            "total_orders": 1,
            "ui_data": [{"order_id": f'{kwargs["site_id"]}-1'}],
            "requires_selection": True,
            "prior_action": "refund",
        },
    )
    monkeypatch.setattr(
        order_tools,
        "get_user_orders",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("legacy site-c order_tools path should not be used")),
    )

    def capture_adapter_call(**kwargs):
        calls.append(kwargs["site_id"])
        return {
            "ui_action": "show_order_list",
            "message": f'{kwargs["site_id"]} orders',
            "total_orders": 1,
            "ui_data": [{"order_id": f'{kwargs["site_id"]}-1'}],
            "requires_selection": True,
            "prior_action": "refund",
        }

    monkeypatch.setattr(adapter_order_tools, "get_user_orders_for_site", capture_adapter_call)

    site_a_registry = setup.resolve_order_tool_registry("site-a")
    site_c_registry = setup.resolve_order_tool_registry("site-c")

    site_a_payload = site_a_registry["list_orders"](
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        action_context="refund",
        requires_selection=True,
    )
    site_c_payload = site_c_registry["list_orders"](
        user_id=1,
        site_id="site-c",
        access_token=None,
        action_context="refund",
        requires_selection=True,
    )

    for payload in (site_a_payload, site_c_payload):
        assert payload["operation"] == "list_orders"
        assert payload["ui_action"] == "show_order_list"
        assert isinstance(payload["message"], str)
        assert isinstance(payload["orders"], list)
        assert isinstance(payload["ui_data"], list)
        assert isinstance(payload["total_orders"], int)
        assert payload["prior_action"] == "refund"
        assert payload["requires_selection"] is True

    assert calls == ["site-a", "site-c"]


def test_order_tool_registry_payload_still_works_for_selection_consumers(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter_order_tools,
        "get_user_orders_for_site",
        lambda **kwargs: {
            "ui_action": "show_order_list",
            "message": "최근 주문입니다.",
            "total_orders": 1,
            "ui_data": [{"order_id": "food-1"}],
            "requires_selection": True,
            "prior_action": "exchange",
        },
    )
    monkeypatch.setattr(
        order_tools,
        "interrupt",
        lambda payload: {"selected_order_id": payload["ui_data"][0]["order_id"]},
    )

    registry = setup.resolve_order_tool_registry("site-a")
    payload = registry["list_orders"](
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        action_context="exchange",
        requires_selection=True,
    )

    assert payload["operation"] == "list_orders"
    assert payload["ui_action"] == "show_order_list"
    assert payload["ui_data"][0]["order_id"] == "food-1"

    selected_order_id = order_tools._require_order_id(
        user_id=1,
        order_id=None,
        action_context="exchange",
        site_id="site-a",
        access_token="food-token",
    )

    assert selected_order_id == "food-1"


def test_order_tool_registry_normalizes_action_contracts(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter_order_tools,
        "get_order_status_via_adapter",
        SimpleNamespace(
            invoke=lambda payload: {
                "order_id": payload["order_id"],
                "status": "delivered",
                "user_id": 1,
                "items": [],
                "total_amount": 12000,
                "ordered_at": "2026-03-23T09:00:00",
            }
        ),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "cancel_order_via_adapter",
        SimpleNamespace(
            invoke=lambda payload: {
                "success": True,
                "message": "주문이 취소되었습니다.",
                "status": "cancelled",
                "order_id": payload["order_id"],
            }
        ),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "register_return_via_adapter",
        SimpleNamespace(
            invoke=lambda payload: {
                "success": True,
                "message": "환불이 접수되었습니다.",
                "status": "refund_requested",
                "order_id": payload["order_id"],
            }
        ),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "register_exchange_via_adapter",
        SimpleNamespace(
            invoke=lambda payload: {
                "success": True,
                "message": "교환이 접수되었습니다.",
                "status": "exchange_requested",
                "order_id": payload["order_id"],
                "new_option_id": payload.get("new_option_id"),
            }
        ),
    )

    registry = setup.resolve_order_tool_registry("site-a")

    status_payload = registry["get_order_status"](
        order_id="site-a-1",
        user_id=1,
        site_id="site-a",
        access_token="food-token",
    )
    cancel_payload = registry["cancel"](
        order_id="site-a-2",
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        confirmed=True,
    )
    refund_payload = registry["refund"](
        order_id="site-a-3",
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        confirmed=True,
    )
    exchange_payload = registry["exchange"](
        order_id="site-a-4",
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        confirmed=True,
        new_option_id="opt-205",
    )

    assert status_payload["operation"] == "get_order_status"
    assert status_payload["status"] == "delivered"
    assert status_payload["order_id"] == "site-a-1"

    assert cancel_payload["operation"] == "cancel"
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["order_id"] == "site-a-2"

    assert refund_payload["operation"] == "refund"
    assert refund_payload["status"] == "refund_requested"
    assert refund_payload["order_id"] == "site-a-3"

    assert exchange_payload["operation"] == "exchange"
    assert exchange_payload["status"] == "exchange_requested"
    assert exchange_payload["order_id"] == "site-a-4"
    assert exchange_payload["new_option_id"] == "opt-205"
