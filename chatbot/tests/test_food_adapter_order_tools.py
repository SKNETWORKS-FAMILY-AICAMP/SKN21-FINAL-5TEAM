import builtins
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.tools import adapter_order_tools
from chatbot.src.adapters import setup as adapter_setup


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

    async def fake_search_products(ctx, filter_input):
        return SimpleNamespace(
            items=[
                SimpleNamespace(id="205", title="교환 옵션", inStock=True, shortDescription=None),
            ]
        )

    adapter.search_products = fake_search_products
    return adapter


def test_adapter_order_tools_imports_without_order_tools_db_dependencies(monkeypatch):
    original_adapter_module = sys.modules.get("chatbot.src.tools.adapter_order_tools")
    original_order_tools_module = sys.modules.get("chatbot.src.tools.order_tools")
    tools_package = sys.modules.get("chatbot.src.tools")
    if tools_package is not None:
        tools_package.__dict__.pop("adapter_order_tools", None)
        tools_package.__dict__.pop("order_tools", None)
    sys.modules.pop("chatbot.src.tools.adapter_order_tools", None)
    sys.modules.pop("chatbot.src.tools.order_tools", None)

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "chatbot.src.tools.order_tools" or name.startswith("ecommerce.backend"):
            raise AssertionError(f"unexpected DB-bound import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("chatbot.src.tools.adapter_order_tools")

    assert hasattr(module, "register_exchange_via_adapter")

    if original_adapter_module is not None:
        sys.modules["chatbot.src.tools.adapter_order_tools"] = original_adapter_module
        if tools_package is not None:
            tools_package.adapter_order_tools = original_adapter_module
    if original_order_tools_module is not None:
        sys.modules["chatbot.src.tools.order_tools"] = original_order_tools_module
        if tools_package is not None:
            tools_package.order_tools = original_order_tools_module


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
        assert input_data.newOptionId == "205"
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
            "new_option_id": "205",
        }
    )

    assert result["success"] is True
    assert result["status"] == "exchange_requested"
    assert result["new_option_id"] == "205"


def test_exchange_via_adapter_requests_option_selection_before_confirmation(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")
    prompted: list[dict] = []
    submitted: list[object] = []

    async def fake_search_products(ctx, filter_input):
        return SimpleNamespace(
            items=[
                SimpleNamespace(id="201", title="새 상품 A", inStock=True, shortDescription=None),
                SimpleNamespace(id="202", title="새 상품 B", inStock=True, shortDescription=None),
            ]
        )

    async def fake_submit_order_action(ctx, input_data):
        submitted.append(input_data)
        return SimpleNamespace(success=True, message="교환이 접수되었습니다.")

    adapter.search_products = fake_search_products
    adapter.submit_order_action = fake_submit_order_action

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_resolve_order_with_confirmation_for_site",
        lambda **kwargs: ("15", None, None),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "interrupt",
        lambda payload: prompted.append(payload) or {"new_option_id": "202"},
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_require_human_confirmation",
        lambda **kwargs: True,
    )

    result = adapter_order_tools.register_exchange_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "15",
        }
    )

    assert prompted == [
        {
            "ui_action": "show_option_list",
            "action": "select_option",
            "message": "교환할 옵션을 선택해주세요.",
            "ui_data": [
                {"option_id": "201", "label": "새 상품 A", "in_stock": True},
                {"option_id": "202", "label": "새 상품 B", "in_stock": True},
            ],
            "prior_action": "exchange",
        }
    ]
    assert submitted and submitted[0].newOptionId == "202"
    assert result["success"] is True
    assert result["status"] == "exchange_requested"


def test_extract_new_option_id_from_resume_preserves_opaque_strings_and_numeric_ids():
    assert adapter_order_tools._extract_new_option_id_from_resume(
        {"new_option_id": "opt-blue-large"}
    ) == "opt-blue-large"
    assert adapter_order_tools._extract_new_option_id_from_resume(
        {"new_option_id": "205"}
    ) == 205
    assert adapter_order_tools._extract_new_option_id_from_resume(
        {"new_option_id": 205}
    ) == 205


def test_exchange_via_adapter_preserves_opaque_option_id_from_selection(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")
    submitted: list[object] = []

    async def fake_search_products(ctx, filter_input):
        return SimpleNamespace(
            items=[
                SimpleNamespace(id="opt-blue-large", title="새 상품 A", inStock=True, shortDescription=None),
                SimpleNamespace(id="opt-red-small", title="새 상품 B", inStock=True, shortDescription=None),
            ]
        )

    async def fake_submit_order_action(ctx, input_data):
        submitted.append(input_data)
        return SimpleNamespace(success=True, message="교환이 접수되었습니다.")

    adapter.search_products = fake_search_products
    adapter.submit_order_action = fake_submit_order_action

    monkeypatch.setattr(
        adapter_order_tools,
        "_build_site_adapter_context",
        lambda **kwargs: (adapter, SimpleNamespace(siteId="site-a")),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_resolve_order_with_confirmation_for_site",
        lambda **kwargs: ("15", None, None),
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "interrupt",
        lambda payload: {"new_option_id": "opt-blue-large"},
    )
    monkeypatch.setattr(
        adapter_order_tools,
        "_require_human_confirmation",
        lambda **kwargs: True,
    )

    result = adapter_order_tools.register_exchange_via_adapter.invoke(
        {
            "user_id": 1,
            "site_id": "site-a",
            "access_token": "food-token",
            "order_id": "15",
        }
    )

    assert submitted and submitted[0].newOptionId == "opt-blue-large"
    assert result["success"] is True
    assert result["new_option_id"] == "opt-blue-large"


def test_exchange_via_adapter_rejects_invalid_option_id(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")
    submitted: list[object] = []

    async def fake_search_products(ctx, filter_input):
        return SimpleNamespace(
            items=[
                SimpleNamespace(id="201", title="새 상품 A", inStock=True, shortDescription=None),
                SimpleNamespace(id="202", title="새 상품 B", inStock=True, shortDescription=None),
            ]
        )

    async def fake_submit_order_action(ctx, input_data):
        submitted.append(input_data)
        return SimpleNamespace(success=True, message="교환이 접수되었습니다.")

    adapter.search_products = fake_search_products
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
            "new_option_id": "999",
        }
    )

    assert submitted == []
    assert result["ui_action"] == "show_option_list"
    assert result["prior_action"] == "exchange"
    assert result["ui_data"] == [
        {"option_id": "201", "label": "새 상품 A", "in_stock": True},
        {"option_id": "202", "label": "새 상품 B", "in_stock": True},
    ]
    assert "show_address_search" not in result
    assert "error" not in result


def test_exchange_via_adapter_returns_selection_payload_when_no_options_available(monkeypatch):
    adapter = _build_adapter_with_order_status("delivered")
    submitted: list[object] = []

    async def fake_search_products(ctx, filter_input):
        return SimpleNamespace(items=[])

    async def fake_submit_order_action(ctx, input_data):
        submitted.append(input_data)
        return SimpleNamespace(success=True, message="교환이 접수되었습니다.")

    adapter.search_products = fake_search_products
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

    assert submitted == []
    assert result["ui_action"] == "show_option_list"
    assert result["ui_data"] == []
    assert "show_address_search" not in result
    assert "error" not in result


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


def test_order_tool_registry_uses_food_adapter_list_contract(monkeypatch):
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

    registry = adapter_setup.resolve_order_tool_registry("site-a")
    payload = registry["list_orders"](
        user_id=1,
        site_id="site-a",
        access_token="food-token",
        action_context="exchange",
        requires_selection=True,
    )

    assert payload["operation"] == "list_orders"
    assert payload["orders"][0]["order_id"] == "food-1"
    assert payload["prior_action"] == "exchange"
