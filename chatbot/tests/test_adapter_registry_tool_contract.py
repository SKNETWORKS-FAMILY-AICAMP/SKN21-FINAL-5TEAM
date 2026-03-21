from __future__ import annotations

import sys
from pathlib import Path

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
        assert payload["ui_action"] == "show_order_list"
        assert isinstance(payload["message"], str)
        assert isinstance(payload["ui_data"], list)
        assert isinstance(payload["total_orders"], int)
        assert payload["prior_action"] == "refund"
        assert payload["requires_selection"] is True

    assert calls == ["site-a", "site-c"]
