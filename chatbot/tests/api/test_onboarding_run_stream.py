from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from fastapi import FastAPI
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot import server_fastapi
from chatbot.server_fastapi import app


class _FakeRedis:
    def __init__(self) -> None:
        self._lists: dict[str, list[str]] = {}

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self._lists.get(key, [])
        if stop < 0:
            stop = len(values) + stop
        if stop < 0:
            return []
        stop = min(stop, len(values) - 1)
        if start >= len(values):
            return []
        return list(values[start : stop + 1])


def _stream_key(run_id: str) -> str:
    return f"onboarding:events:{run_id}"


def _seed_events(store: _FakeRedis, run_id: str, *events: dict) -> None:
    key = _stream_key(run_id)
    for event in events:
        store.rpush(key, json.dumps(event, ensure_ascii=False))


def _iter_sse_events(response, limit: int) -> list[dict]:
    payloads: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        payloads.append(json.loads(line[6:]))
        if len(payloads) >= limit:
            break
    return payloads


def test_onboarding_run_stream_requires_internal_bearer_token():
    client = TestClient(app)
    response = client.get("/api/v1/onboarding/runs/run-001/events")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid onboarding internal token"


def test_onboarding_run_stream_replays_existing_events_and_tails_new_ones():
    run_id = "food-run-stream"
    store = _FakeRedis()
    _seed_events(
        store,
        run_id,
        {"run_id": run_id, "event": "run.created", "payload": {"site": "food"}},
        {"run_id": run_id, "event": "job.started", "payload": {"role": "Planner", "job_id": f"{run_id}:Planner:1"}},
    )

    app.state.onboarding_event_store = store
    app.state.onboarding_stream_poll_interval = 0.001
    app.state.onboarding_stream_keepalive_interval = 100
    app.state.onboarding_stream_max_idle_polls = 200
    app.state.onboarding_stream_max_events = 3
    token = "test-internal-token"

    from chatbot.src.core.config import settings

    original_token = settings.ONBOARDING_INTERNAL_API_TOKEN
    settings.ONBOARDING_INTERNAL_API_TOKEN = token

    client = TestClient(app)
    delayed_seed = threading.Timer(
        0.02,
        lambda: _seed_events(
            store,
            run_id,
            {"run_id": run_id, "event": "job.completed", "payload": {"role": "Planner", "job_id": f"{run_id}:Planner:1"}},
        ),
    )
    try:
        delayed_seed.start()
        with client.stream(
            "GET",
            f"/api/v1/onboarding/runs/{run_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            payloads = _iter_sse_events(response, limit=3)
    finally:
        delayed_seed.cancel()
        settings.ONBOARDING_INTERNAL_API_TOKEN = original_token
        del app.state.onboarding_event_store
        del app.state.onboarding_stream_poll_interval
        del app.state.onboarding_stream_keepalive_interval
        del app.state.onboarding_stream_max_idle_polls
        del app.state.onboarding_stream_max_events

    assert response.status_code == 200
    assert payloads == [
        {"run_id": run_id, "event": "run.created", "payload": {"site": "food"}},
        {"run_id": run_id, "event": "job.started", "payload": {"role": "Planner", "job_id": f"{run_id}:Planner:1"}},
        {"run_id": run_id, "event": "job.completed", "payload": {"role": "Planner", "job_id": f"{run_id}:Planner:1"}},
    ]


def test_onboarding_run_stream_returns_401_for_wrong_internal_token():
    run_id = "food-run-stream-auth"
    store = _FakeRedis()
    app.state.onboarding_event_store = store

    from chatbot.src.core.config import settings

    original_token = settings.ONBOARDING_INTERNAL_API_TOKEN
    settings.ONBOARDING_INTERNAL_API_TOKEN = "expected-token"

    client = TestClient(app)
    try:
        response = client.get(
            f"/api/v1/onboarding/runs/{run_id}/events",
            headers={"Authorization": "Bearer wrong-token"},
        )
    finally:
        settings.ONBOARDING_INTERNAL_API_TOKEN = original_token
        del app.state.onboarding_event_store

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid onboarding internal token"


def test_onboarding_run_stream_can_start_empty_and_emit_later_event():
    run_id = "food-run-empty"
    store = _FakeRedis()
    app.state.onboarding_event_store = store
    app.state.onboarding_stream_poll_interval = 0.001
    app.state.onboarding_stream_keepalive_interval = 100
    app.state.onboarding_stream_max_idle_polls = 200
    app.state.onboarding_stream_max_events = 1

    from chatbot.src.core.config import settings

    original_token = settings.ONBOARDING_INTERNAL_API_TOKEN
    settings.ONBOARDING_INTERNAL_API_TOKEN = "empty-token"

    client = TestClient(app)
    delayed_seed = threading.Timer(
        0.02,
        lambda: _seed_events(
            store,
            run_id,
            {"run_id": run_id, "event": "run.created", "payload": {"site": "food"}},
        ),
    )
    try:
        delayed_seed.start()
        with client.stream(
            "GET",
            f"/api/v1/onboarding/runs/{run_id}/events",
            headers={"Authorization": "Bearer empty-token"},
        ) as response:
            payloads = _iter_sse_events(response, limit=1)
    finally:
        delayed_seed.cancel()
        settings.ONBOARDING_INTERNAL_API_TOKEN = original_token
        del app.state.onboarding_event_store
        del app.state.onboarding_stream_poll_interval
        del app.state.onboarding_stream_keepalive_interval
        del app.state.onboarding_stream_max_idle_polls
        del app.state.onboarding_stream_max_events

    assert response.status_code == 200
    assert payloads == [
        {"run_id": run_id, "event": "run.created", "payload": {"site": "food"}}
    ]


def test_shared_app_chat_route_accepts_site_aware_request(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def fake_resolve_site_adapter(site_id: str):
        calls.append(("resolve", site_id))
        return SimpleNamespace(site_id=site_id)

    def fake_invoke(state, config):
        user_info = state["user_info"]
        calls.append(("invoke", user_info.get("site_id")))
        return {
            "messages": [AIMessage(content="ok")],
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

    monkeypatch.setattr(server_fastapi.adapter_setup, "resolve_site_adapter", fake_resolve_site_adapter)
    monkeypatch.setattr(server_fastapi.graph_app, "invoke", fake_invoke)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={
            "message": "주문 보여줘",
            "site_id": "site-a",
            "access_token": "bridge-token",
            "user_id": 3,
            "user_name": "Tester",
        },
    )

    assert response.status_code == 200
    assert calls == [("resolve", "site-a"), ("invoke", "site-a")]
    assert response.json()["state"]["user_info"]["site_id"] == "site-a"
    assert response.json()["state"]["user_info"]["access_token"] == "bridge-token"


def test_standalone_server_exposes_shared_stream_route(monkeypatch):
    from chatbot.src.api.v1.endpoints import chat as chat_module

    app.dependency_overrides[chat_module.get_current_user_optional] = lambda: SimpleNamespace(
        id=7,
        email="tester@example.com",
        name="Tester",
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "message": "주문 보여줘",
                "site_id": "site-a",
                "access_token": "bridge-token",
            },
        )
    finally:
        app.dependency_overrides.pop(chat_module.get_current_user_optional, None)

    assert response.status_code != 404


def test_stream_endpoint_preserves_previous_site_and_access_token_on_follow_up_turn(monkeypatch):
    from chatbot.src.api.v1.endpoints import chat as chat_module

    captured: dict[str, object] = {}

    async def fake_astream_events(stream_input, version, config):
        captured["stream_input"] = stream_input
        captured["config"] = config
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "messages": [AIMessage(content="후속 응답")],
                    "completed_tasks": [],
                    "ui_action_required": None,
                    "order_context": {},
                    "search_context": {},
                    "user_info": stream_input["user_info"],
                    "llm_provider": stream_input["llm_provider"],
                    "llm_model": stream_input["llm_model"],
                    "conversation_summary": None,
                }
            },
        }

    monkeypatch.setattr(chat_module.adapter_setup, "resolve_site_adapter", lambda site_id: SimpleNamespace(site_id=site_id))
    monkeypatch.setattr(chat_module.graph_app, "astream_events", fake_astream_events)
    monkeypatch.setattr(chat_module, "_append_session_turn_log", lambda **kwargs: None)

    test_app = FastAPI()
    test_app.include_router(chat_module.router)
    test_app.dependency_overrides[chat_module.get_current_user_optional] = lambda: SimpleNamespace(
        id=1,
        name="Tester",
        email="tester@example.com",
    )

    client = TestClient(test_app)
    response = client.post(
        "/stream",
        json={
            "message": "다음 주문도 보여줘",
            "previous_state": {
                "conversation_id": "conv-123",
                "user_info": {
                    "site_id": "site-a",
                    "access_token": "bridge-token",
                },
            },
        },
    )

    assert response.status_code == 200
    assert captured["stream_input"]["user_info"]["site_id"] == "site-a"
    assert captured["stream_input"]["user_info"]["access_token"] == "bridge-token"


def test_stream_endpoint_accepts_site_a_bridge_access_token_without_chatbot_cookie(monkeypatch):
    from chatbot.src.api.v1.endpoints import chat as chat_module

    captured: dict[str, object] = {}

    class _FakeAdapter:
        site_id = "site-a"

        async def validate_auth(self, ctx):
            captured["auth_ctx"] = ctx
            return SimpleNamespace(id="7", email="tester@example.com", name="Tester")

    async def fake_astream_events(stream_input, version, config):
        captured["stream_input"] = stream_input
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "messages": [AIMessage(content="브리지 인증 응답")],
                    "completed_tasks": [],
                    "ui_action_required": None,
                    "order_context": {},
                    "search_context": {},
                    "user_info": stream_input["user_info"],
                    "llm_provider": stream_input["llm_provider"],
                    "llm_model": stream_input["llm_model"],
                    "conversation_summary": None,
                }
            },
        }

    monkeypatch.setattr(chat_module.adapter_setup, "resolve_site_adapter", lambda site_id: _FakeAdapter())
    monkeypatch.setattr(chat_module.graph_app, "astream_events", fake_astream_events)
    monkeypatch.setattr(chat_module, "_append_session_turn_log", lambda **kwargs: None)

    test_app = FastAPI()
    test_app.include_router(chat_module.router)

    client = TestClient(test_app)
    response = client.post(
        "/stream",
        json={
            "message": "주문 보여줘",
            "site_id": "site-a",
            "access_token": "bridge-token",
        },
    )

    assert response.status_code == 200
    assert captured["auth_ctx"].siteId == "site-a"
    assert captured["auth_ctx"].accessToken == "bridge-token"
    assert captured["stream_input"]["user_info"]["id"] == "7"
    assert captured["stream_input"]["user_info"]["site_id"] == "site-a"
    assert captured["stream_input"]["user_info"]["access_token"] == "bridge-token"
