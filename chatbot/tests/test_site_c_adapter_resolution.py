import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.adapters.schema import (
    AuthenticatedContext,
    GetOrderStatusInput,
    OrderActionReason,
    OrderActionType,
    SubmitOrderActionInput,
)
from chatbot.src.adapters.site_c.adapter import SiteCAdapter
from chatbot.src.adapters.site_c.client import SiteCClient


def _build_ctx() -> AuthenticatedContext:
    return AuthenticatedContext(siteId="site-c", userId="1", accessToken="token-123")


def _build_order_payload(order_id: int = 42, order_number: str = "ORD-20260303-0002") -> dict:
    return {
        "id": order_id,
        "user_id": 1,
        "order_number": order_number,
        "status": "delivered",
        "total_amount": 10000,
        "created_at": "2026-03-03T10:00:00",
        "updated_at": "2026-03-03T10:00:00",
        "items": [],
        "payment": None,
        "shipping_info": None,
    }


@pytest.mark.anyio
async def test_get_order_status_resolves_order_number_before_fetch(monkeypatch):
    calls: list[tuple[str, str]] = []
    client = SiteCClient(base_url="http://localhost:8000")
    adapter = SiteCAdapter(client)

    async def fake_get_order_by_number(order_number: str, headers: dict):
        calls.append(("number", order_number))
        return _build_order_payload(order_id=42, order_number=order_number)

    async def fake_get_order(user_id: str, input_data: GetOrderStatusInput, headers: dict):
        calls.append(("detail", input_data.orderId))
        return _build_order_payload(order_id=int(input_data.orderId))

    monkeypatch.setattr(client, "get_order_by_number", fake_get_order_by_number)
    monkeypatch.setattr(client, "get_order", fake_get_order)

    result = await adapter.get_order_status(_build_ctx(), GetOrderStatusInput(orderId="ORD-20260303-0002"))

    assert result.order.orderId == "42"
    assert calls == [("number", "ORD-20260303-0002"), ("detail", "42")]


@pytest.mark.anyio
async def test_submit_order_action_uses_resolved_internal_order_id(monkeypatch):
    client = SiteCClient(base_url="http://localhost:8000")
    adapter = SiteCAdapter(client)
    calls: list[tuple[str, str]] = []

    async def fake_get_order_by_number(order_number: str, headers: dict):
        calls.append(("number", order_number))
        return _build_order_payload(order_id=77, order_number=order_number)

    async def fake_get_order(user_id: str, input_data: GetOrderStatusInput, headers: dict):
        calls.append(("detail", input_data.orderId))
        return _build_order_payload(order_id=int(input_data.orderId))

    async def fake_submit_refund(user_id: str, input_data: SubmitOrderActionInput, headers: dict):
        calls.append(("refund", input_data.orderId))
        return {"message": "환불 요청이 접수되었습니다."}

    monkeypatch.setattr(client, "get_order_by_number", fake_get_order_by_number)
    monkeypatch.setattr(client, "get_order", fake_get_order)
    monkeypatch.setattr(client, "submit_refund", fake_submit_refund)

    result = await adapter.submit_order_action(
        _build_ctx(),
        SubmitOrderActionInput(
            orderId="ORD-20260303-0002",
            actionType=OrderActionType.REFUND,
            reasonCode=OrderActionReason.CHANGED_MIND,
            reasonText="단순 변심",
        ),
    )

    assert result.success is True
    assert calls == [
        ("number", "ORD-20260303-0002"),
        ("detail", "77"),
        ("refund", "77"),
    ]
