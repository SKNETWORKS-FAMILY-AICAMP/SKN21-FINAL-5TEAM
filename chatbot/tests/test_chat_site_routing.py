from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot import server_fastapi
from chatbot.src.adapters import setup as adapter_setup
from chatbot.src.core.config import settings
from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract


def _stub_adapter(site_id: str):
    if site_id == "site-a":
        contract = ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name="session_token",
        )
    elif site_id == "site-b":
        contract = ResolvedAuthContract(transport="bearer_token")
    else:
        contract = ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name="access_token",
        )
    return SimpleNamespace(site_id=site_id, auth_contract=contract)


def test_chat_request_routes_site_adapter_before_graph_invoke(monkeypatch):
    calls: list[tuple[str, str | None, str | None]] = []

    def fake_resolve_site_adapter(site_id: str):
        calls.append(("resolve", site_id, None))
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        user_info = state["user_info"]
        calls.append(("invoke", user_info.get("site_id"), user_info.get("access_token")))
        assert user_info["site_id"] == "site-a"
        assert user_info["access_token"] == "bridge-token"
        return {
            "messages": [AIMessage(content="주문 목록을 불러왔습니다.")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": user_info,
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "주문 보여줘",
            "site_id": "site-a",
            "access_token": "bridge-token",
            "user_id": 7,
            "user_name": "Tester",
            "user_email": "tester@example.com",
        },
    )

    assert response.status_code == 200
    assert calls == [
        ("resolve", "site-a", None),
        ("invoke", "site-a", "bridge-token"),
    ]
    assert response.json()["state"]["user_info"]["site_id"] == "site-a"
    assert response.json()["state"]["user_info"]["access_token"] == "bridge-token"


def test_shared_app_chat_route_preserves_previous_site_on_follow_up_turn(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def fake_resolve_site_adapter(site_id: str):
        calls.append(("resolve", site_id))
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        user_info = state["user_info"]
        calls.append(("invoke", user_info.get("site_id")))
        assert user_info["site_id"] == "site-a"
        return {
            "messages": [AIMessage(content="후속 응답")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": user_info,
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "다음 주문도 보여줘",
            "previous_state": {
                "user_info": {
                    "site_id": "site-a",
                    "access_token": "bridge-token",
                },
                "conversation_id": "conv-123",
                "messages": [],
            },
            "access_token": "bridge-token",
            "user_id": 7,
            "user_name": "Tester",
        },
    )

    assert response.status_code == 200
    assert calls == [
        ("resolve", "site-a"),
        ("invoke", "site-a"),
    ]
    assert response.json()["state"]["user_info"]["site_id"] == "site-a"


def test_chat_request_uses_server_llm_defaults_when_request_omits_model(monkeypatch):
    calls: list[tuple[str, str | None, str | None]] = []

    def fake_resolve_site_adapter(site_id: str):
        calls.append(("resolve", site_id, None))
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        calls.append(("invoke", state["llm_provider"], state["llm_model"]))
        assert state["llm_provider"] == "local"
        assert state["llm_model"] == "Qwen/server-default"
        return {
            "messages": [AIMessage(content="기본 모델 응답")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": state["user_info"],
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(settings, "LLM_PROVIDER", "local")
    monkeypatch.setattr(settings, "HF_MODEL_ID", "Qwen/server-default")
    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "주문 보여줘",
            "site_id": "site-a",
        },
    )

    assert response.status_code == 200
    assert calls == [
        ("resolve", "site-a", None),
        ("invoke", "local", "Qwen/server-default"),
    ]


def test_chat_request_normalizes_huggingface_alias_to_local(monkeypatch):
    def fake_resolve_site_adapter(site_id: str):
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        assert state["llm_provider"] == "local"
        assert state["llm_model"] == "Qwen/override"
        return {
            "messages": [AIMessage(content="정규화 응답")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": state["user_info"],
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "주문 보여줘",
            "site_id": "site-a",
            "provider": "huggingface",
            "model": "Qwen/override",
        },
    )

    assert response.status_code == 200


def test_chat_request_preserves_cookie_auth_material_in_graph_state(monkeypatch):
    def fake_resolve_site_adapter(site_id: str):
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        assert state["user_info"]["site_id"] == "site-a"
        assert state["user_info"]["access_token"] == "food-token"
        assert state["user_info"]["cookies"] == {"session_token": "food-token"}
        return {
            "messages": [AIMessage(content="쿠키 주문 목록")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": state["user_info"],
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "쿠키 주문 보여줘",
            "site_id": "site-a",
            "user_id": 7,
            "user_name": "Tester",
        },
        cookies={"session_token": "food-token"},
    )

    assert response.status_code == 200
    assert response.json()["state"]["user_info"]["cookies"] == {"session_token": "food-token"}


def test_shared_app_chat_route_reuses_previous_cookie_auth_material_when_request_omits_it(monkeypatch):
    def fake_resolve_site_adapter(site_id: str):
        return _stub_adapter(site_id)

    def fake_invoke(state, config):
        assert state["user_info"]["site_id"] == "site-a"
        assert state["user_info"]["access_token"] == "food-token"
        assert state["user_info"]["cookies"] == {"session_token": "food-token"}
        return {
            "messages": [AIMessage(content="이전 쿠키 재사용")],
            "completed_tasks": [],
            "ui_action_required": None,
            "awaiting_interrupt": False,
            "interrupts": [],
            "order_context": {},
            "search_context": {},
            "user_info": state["user_info"],
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "conversation_summary": None,
        }

    monkeypatch.setattr(adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter, raising=False)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(server_fastapi.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "이전 세션으로 계속",
            "previous_state": {
                "user_info": {
                    "site_id": "site-a",
                    "access_token": "food-token",
                    "cookies": {"session_token": "food-token"},
                },
                "conversation_id": "conv-cookie-1",
                "messages": [],
            },
            "user_id": 7,
            "user_name": "Tester",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"]["user_info"]["cookies"] == {"session_token": "food-token"}
