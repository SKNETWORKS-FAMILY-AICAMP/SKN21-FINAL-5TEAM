from __future__ import annotations

import json
import os
import sys
import threading
from types import ModuleType
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

fake_langchain_ollama = ModuleType("langchain_ollama")


class _FakeChatOllama:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_langchain_ollama.ChatOllama = _FakeChatOllama
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)

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


def test_onboarding_run_stream_replays_runtime_completion_event_payload():
    run_id = "food-run-runtime-completion-stream"
    store = _FakeRedis()
    _seed_events(
        store,
        run_id,
        {
            "run_id": run_id,
            "event": "job.completed",
            "payload": {
                "role": "Validator",
                "job_id": f"{run_id}:Validator:1",
                "launcher_visible": True,
                "auth_bootstrap_passed": True,
                "chat_stream_passed": True,
            },
        },
    )

    app.state.onboarding_event_store = store
    app.state.onboarding_stream_poll_interval = 0.001
    app.state.onboarding_stream_keepalive_interval = 100
    app.state.onboarding_stream_max_idle_polls = 5
    app.state.onboarding_stream_max_events = 1

    from chatbot.src.core.config import settings

    original_token = settings.ONBOARDING_INTERNAL_API_TOKEN
    settings.ONBOARDING_INTERNAL_API_TOKEN = "runtime-token"

    client = TestClient(app)
    try:
        with client.stream(
            "GET",
            f"/api/v1/onboarding/runs/{run_id}/events",
            headers={"Authorization": "Bearer runtime-token"},
        ) as response:
            payloads = _iter_sse_events(response, limit=1)
    finally:
        settings.ONBOARDING_INTERNAL_API_TOKEN = original_token
        del app.state.onboarding_event_store
        del app.state.onboarding_stream_poll_interval
        del app.state.onboarding_stream_keepalive_interval
        del app.state.onboarding_stream_max_idle_polls
        del app.state.onboarding_stream_max_events

    assert response.status_code == 200
    assert payloads == [
        {
            "run_id": run_id,
            "event": "job.completed",
            "payload": {
                "role": "Validator",
                "job_id": f"{run_id}:Validator:1",
                "launcher_visible": True,
                "auth_bootstrap_passed": True,
                "chat_stream_passed": True,
            },
        }
    ]
