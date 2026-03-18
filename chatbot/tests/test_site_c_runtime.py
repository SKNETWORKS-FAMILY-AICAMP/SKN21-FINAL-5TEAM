import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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


def test_get_site_adapter_supports_site_a():
    adapter = adapter_order_tools._get_site_adapter("site-a")

    assert adapter.site_id == "site-a"


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


def test_build_current_state_accepts_food_session_token():
    state = _build_current_state(
        request=DummyRequest(site_id="site-a"),
        current_user=DummyUser(),
        previous_state={},
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-2",
        turn_id="turn-2",
        access_token="session-token-123",
    )

    assert state["user_info"]["site_id"] == "site-a"
    assert state["user_info"]["access_token"] == "session-token-123"
