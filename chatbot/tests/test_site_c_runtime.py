import sys
import json
import os
import subprocess
import asyncio
from pathlib import Path
import types
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

langchain_ollama = types.ModuleType("langchain_ollama")


class _DummyChatOllama:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


langchain_ollama.ChatOllama = _DummyChatOllama
sys.modules.setdefault("langchain_ollama", langchain_ollama)

from chatbot.src.adapters import setup as adapter_setup
from chatbot.src.adapters.site_a.adapter import SiteAAdapter
from chatbot.src.adapters.site_a.client import SiteAClient
from chatbot.src.adapters.site_b.adapter import SiteBAdapter
from chatbot.src.adapters.site_b.client import SiteBClient
from chatbot.src.adapters.site_c.adapter import SiteCAdapter
from chatbot.src.adapters.site_c.client import SiteCClient
from chatbot.src.api.v1.endpoints.chat import _build_current_state, _resolve_authenticated_current_user
from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract
from chatbot.src.schemas.chat import ChatRequest as SharedChatRequest
from chatbot.src.tools import adapter_order_tools


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = FRONTEND_ROOT / "node_modules" / ".bin" / "tsc"


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


def test_shared_chat_request_accepts_bridge_access_token():
    request = SharedChatRequest(message="안녕", access_token="bridge-token")

    assert request.access_token == "bridge-token"


def test_shared_chat_request_accepts_bridge_user_id():
    request = SharedChatRequest(message="안녕", access_token="bridge-token", user_id="7")

    assert request.user_id == "7"


def test_build_current_state_preserves_previous_site_id_on_follow_up_turn():
    previous_state = {
        "user_info": {
            "site_id": "site-a",
            "access_token": "bridge-token",
        }
    }

    state = _build_current_state(
        request=DummyRequest(site_id=None),
        current_user=DummyUser(),
        previous_state=previous_state,
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-3",
        turn_id="turn-3",
        access_token="bridge-token",
    )

    assert state["user_info"]["site_id"] == "site-a"
    assert state["user_info"]["access_token"] == "bridge-token"


def test_resolve_authenticated_current_user_uses_bridge_user_id_on_initial_request(monkeypatch):
    captured: dict[str, str] = {}

    class StubAdapter:
        site_id = "site-c"
        auth_contract = ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name="access_token",
        )

        async def validate_auth(self, ctx):
            captured["site_id"] = ctx.siteId
            captured["user_id"] = ctx.userId
            captured["access_token"] = ctx.accessToken
            return SimpleNamespace(id="7", email="tester@example.com", name="Tester")

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", lambda site_id: StubAdapter())

    current_user = asyncio.run(
        _resolve_authenticated_current_user(
            request=SharedChatRequest(
                message="환불해줘",
                site_id="site-c",
                access_token="bridge-token",
                user_id="7",
            ),
            http_request=SimpleNamespace(cookies={"access_token": "bridge-token"}),
        )
    )

    assert captured == {
        "site_id": "site-c",
        "user_id": "7",
        "access_token": "bridge-token",
    }
    assert current_user.id == "7"


def test_resolve_authenticated_current_user_uses_session_cookie_auth_contract(monkeypatch):
    captured: dict[str, object] = {}

    class StubAdapter:
        site_id = "site-a"
        auth_contract = ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name="session_token",
        )

        async def validate_auth(self, ctx):
            captured["site_id"] = ctx.siteId
            captured["user_id"] = ctx.userId
            captured["access_token"] = ctx.accessToken
            captured["cookies"] = ctx.cookies
            return SimpleNamespace(id="7", email="tester@example.com", name="Tester")

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", lambda site_id: StubAdapter())

    current_user = asyncio.run(
        _resolve_authenticated_current_user(
            request=SharedChatRequest(
                message="주문 보여줘",
                site_id="site-a",
                user_id="7",
            ),
            http_request=SimpleNamespace(cookies={"session_token": "food-cookie"}, headers={}),
        )
    )

    assert captured == {
        "site_id": "site-a",
        "user_id": "7",
        "access_token": "food-cookie",
        "cookies": {"session_token": "food-cookie"},
    }
    assert current_user.id == "7"


def test_static_adapters_expose_site_auth_contracts():
    food_adapter = SiteAAdapter(client=SiteAClient(base_url="http://food.example"))
    bilyeo_adapter = SiteBAdapter(client=SiteBClient(base_url="http://bilyeo.example"))
    ecommerce_adapter = SiteCAdapter(client=SiteCClient(base_url="http://ecommerce.example"))

    assert food_adapter.auth_contract.transport == "session_cookie"
    assert food_adapter.auth_contract.session_cookie_name == "session_token"
    assert bilyeo_adapter.auth_contract.transport == "bearer_token"
    assert ecommerce_adapter.auth_contract.transport == "session_cookie"
    assert ecommerce_adapter.auth_contract.session_cookie_name == "access_token"


def test_shared_widget_source_preserves_bridge_user_id_contract():
    source = (
        REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "ChatbotWidget.tsx"
    ).read_text(encoding="utf-8")

    assert 'userId: String(payload.user_id ?? payload.user?.id ?? "")' in source
    assert 'user_id: String(payload.user_id ?? payload.user?.id ?? "")' in source
    assert "user_id: args.bootstrap.user_id" in source
