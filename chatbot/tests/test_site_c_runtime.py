import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.adapters.schema import AdapterError
from chatbot.src.adapters import setup as adapter_setup
from chatbot.src.api.v1.endpoints.chat import _build_current_state
from chatbot.src.tools import adapter_order_tools


class DummyUser:
    def __init__(self, user_id: int = 1, name: str = "Tester", email: str = "tester@example.com"):
        self.id = user_id
        self.name = name
        self.email = email


class DummyRequest:
    def __init__(self, message: str = "환불해줘", site_id: str | None = "site-c"):
        self.message = message
        self.site_id = site_id


def test_get_site_adapter_rejects_non_site_c():
    with pytest.raises(AdapterError):
        adapter_order_tools._get_site_adapter("site-a")


def test_resolve_ecommerce_backend_url_uses_localhost_outside_docker(monkeypatch):
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    monkeypatch.setattr(adapter_setup.os.path, "exists", lambda path: False)

    assert adapter_setup.resolve_ecommerce_backend_url() == "http://localhost:8000"


def test_build_current_state_includes_access_token():
    state = _build_current_state(
        request=DummyRequest(),
        current_user=DummyUser(),
        previous_state={},
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-1",
        turn_id="turn-1",
        access_token="token-123",
    )

    assert state["user_info"]["site_id"] == "site-c"
    assert state["user_info"]["access_token"] == "token-123"


def test_refund_returns_clear_error_for_unsupported_site():
    result = adapter_order_tools.register_return_via_adapter.invoke({
        "order_id": "ORD-1",
        "user_id": 1,
        "site_id": "site-a",
    })

    assert result["error"] == "현재 이 챗봇은 ecommerce(site-c)만 지원합니다."
