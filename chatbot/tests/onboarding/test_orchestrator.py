import sys
import typing
from types import ModuleType
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import json
import os
from typing import Any, Callable

import pytest

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

fake_langchain_ollama = ModuleType("langchain_ollama")


class _FakeChatOllama:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_langchain_ollama.ChatOllama = _FakeChatOllama
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.recovery_planner import build_recovery_plan
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._expiry: dict[str, int] = {}

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key) or {})

    def sadd(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key) or set())

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def lpop(self, key: str) -> str | None:
        values = self._lists.get(key, [])
        if not values:
            return None
        return values.pop(0)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self._lists.get(key, [])
        if stop < 0:
            stop = len(values) + stop
        stop = min(stop, len(values) - 1)
        if start >= len(values):
            return []
        return list(values[start : stop + 1])

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._expiry[key] = ttl_seconds

from chatbot.src.onboarding.orchestrator import run_onboarding_generation
from chatbot.src.onboarding.redis_store import RedisRunJobStore
from chatbot.src.onboarding.role_runner import RoleRunner
from chatbot.src.onboarding import orchestrator as orchestrator_module


def _successful_smoke_results() -> list[dict]:
    return [
        {
            "step": "login",
            "step_id": "login",
            "required": True,
            "category": "auth",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"ok": true}',
            "stderr": "",
            "request": {"method": "POST", "url": "http://127.0.0.1:8000/api/login", "headers": {}},
            "response": {"status": 200, "headers": {"Set-Cookie": "session=abc"}, "body": '{"ok": true}'},
            "exports": {"login.cookies": "session=abc"},
        },
        {
            "step": "chat-auth-token",
            "step_id": "chat-auth-token",
            "required": True,
            "category": "auth",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"access_token": "token"}',
            "stderr": "",
            "request": {"method": "POST", "url": "http://127.0.0.1:8000/api/chat/auth-token", "headers": {"Cookie": "session=abc"}},
            "response": {"status": 200, "headers": {}, "body": '{"access_token": "token"}'},
            "exports": {"chat_auth.access_token": "token"},
        },
        {
            "step": "product-api",
            "step_id": "product-api",
            "required": True,
            "category": "catalog",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"items": [{"id": 1}]}',
            "stderr": "",
            "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/products/", "headers": {"Authorization": "Bearer token"}},
            "response": {"status": 200, "headers": {}, "body": '{"items": [{"id": 1}]}'},
            "exports": {"product.first_item": "{'id': 1}"},
        },
        {
            "step": "order-api",
            "step_id": "order-api",
            "required": True,
            "category": "orders",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"orders": [{"id": 7}]}',
            "stderr": "",
            "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/orders/", "headers": {"Authorization": "Bearer token"}},
            "response": {"status": 200, "headers": {}, "body": '{"orders": [{"id": 7}]}'},
            "exports": {"order.first_order": "{'id': 7}"},
        },
    ]


def _successful_session_smoke_results() -> list[dict]:
    return [
        {
            "step": "login",
            "step_id": "login",
            "required": True,
            "category": "auth",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"ok": true}',
            "stderr": "",
            "request": {"method": "POST", "url": "http://127.0.0.1:8000/api/users/login/", "headers": {}},
            "response": {"status": 200, "headers": {"Set-Cookie": "sessionid=abc"}, "body": '{"ok": true}'},
            "exports": {"login.cookies": "sessionid=abc"},
        },
        {
            "step": "session-me",
            "step_id": "session-me",
            "required": True,
            "category": "auth",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"user": {"id": 7}}',
            "stderr": "",
            "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/users/me/", "headers": {"Cookie": "sessionid=abc"}},
            "response": {"status": 200, "headers": {}, "body": '{"user": {"id": 7}}'},
            "exports": {"login.user_id": "7"},
        },
        {
            "step": "product-api",
            "step_id": "product-api",
            "required": True,
            "category": "catalog",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"items": [{"id": 1}]}',
            "stderr": "",
            "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/products/", "headers": {"Cookie": "sessionid=abc"}},
            "response": {"status": 200, "headers": {}, "body": '{"items": [{"id": 1}]}'},
            "exports": {"product.first_item": "{'id': 1}"},
        },
        {
            "step": "order-api",
            "step_id": "order-api",
            "required": True,
            "category": "orders",
            "timed_out": False,
            "returncode": 0,
            "stdout": '{"orders": [{"id": 7}]}',
            "stderr": "",
            "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/orders/", "headers": {"Cookie": "sessionid=abc"}},
            "response": {"status": 200, "headers": {}, "body": '{"orders": [{"id": 7}]}'},
            "exports": {"order.first_order": "{'id': 7}"},
        },
    ]


def _simple_agent_response(role: str, context: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if role == "Generator":
        metadata.update(
            {
                "proposed_files": list(context.get("proposed_files") or []),
                "proposed_patches": list(context.get("proposed_patches") or []),
            }
        )
    if role == "Validator":
        metadata.update(
            {
                "failed_steps": list(context.get("failed_steps") or []),
                "failure_count": int(context.get("failure_count") or 0),
                "validation_status": "passed" if context.get("passed") else "failed",
                "approval_recommendation": "request_export_approval"
                if context.get("passed")
                else "diagnose_failure",
            }
        )
    return {
        "claim": f"{role} completed",
        "evidence": list(context.get("evidence") or []),
        "confidence": 0.7,
        "risk": "low",
        "next_action": "continue",
        "blocking_issue": "",
        "metadata": metadata,
    }


def _build_simple_role_runner(
    diagnostician_responder: Callable[[dict[str, Any]], dict[str, Any]]
) -> RoleRunner:
    responders = {
        role: (lambda role: lambda context: _simple_agent_response(role, context))(role)
        for role in ["Analyzer", "Planner", "Generator", "Validator"]
    }
    responders["Diagnostician"] = diagnostician_responder
    return RoleRunner(responders=responders)


def test_run_validation_with_retries_type_hints_resolve_agent_message():
    hints = typing.get_type_hints(orchestrator_module._run_validation_with_retries)

    assert hints["run_role_with_events"] == Callable[..., orchestrator_module.AgentMessage] | None


def test_run_onboarding_generation_creates_run_bundle_and_runtime_workspace(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **_: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id="food-run-001",
            agent_version="test-v1",
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    run_root = generated_root / "food" / "food-run-001"
    runtime_workspace = runtime_root / "food" / "food-run-001" / "workspace"

    assert result["run_root"] == str(run_root)
    assert result["runtime_workspace"] == str(runtime_workspace)

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis"]["product_api"] == ["/api/products/"]
    assert "patches/backend_chat_auth_route.patch" in manifest["patch_targets"]

    assert (run_root / "files" / "backend" / "chat_auth.py").exists()
    assert (run_root / "patches" / "backend_chat_auth_route.patch").exists()
    assert (run_root / "files" / "backend" / "order_adapter_client.py").exists()
    assert (run_root / "files" / "backend" / "product_adapter_client.py").exists()
    assert (run_root / "patches" / "frontend_widget_mount.patch").exists()
    assert (run_root / "reports" / "smoke-results.json").exists()
    assert (run_root / "reports" / "smoke-summary.json").exists()
    assert runtime_workspace.exists()
    frontend_build_validation = run_root / "reports" / "frontend-build-validation.json"
    assert frontend_build_validation.exists()
    assert result["frontend_build_validation_path"] == str(frontend_build_validation)

    smoke_results = json.loads((run_root / "reports" / "smoke-results.json").read_text(encoding="utf-8"))
    assert len(smoke_results) >= 1
    assert smoke_results[0]["returncode"] == 0

    smoke_summary = json.loads((run_root / "reports" / "smoke-summary.json").read_text(encoding="utf-8"))
    assert smoke_summary["passed"] is True
    assert smoke_summary["required_failures"] == []


def test_run_onboarding_generation_exposes_runtime_completion_loop_path_placeholder(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **_: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id="food-run-runtime-loop",
            agent_version="test-v1",
            approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    assert result["runtime_completion_path"].endswith("reports/runtime-completion.json")


def test_run_onboarding_generation_uses_session_native_chain_for_cookie_auth(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "foodshop").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return request.COOKIES.get('sessionid')\n\ndef me(request):\n    return request.COOKIES.get('sessionid')\n\ndef logout(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "users" / "urls.py").write_text(
        'urlpatterns = [path("login/", views.login), path("me/", views.me), path("logout/", views.logout)]\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "foodshop" / "urls.py").write_text(
        'urlpatterns = [path("api/users/", include("users.urls")), path("api/products/", include("products.urls")), path("api/orders/", include("orders.urls"))]\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    captured: dict[str, Any] = {}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan, **kwargs):
        captured["step_ids"] = [step.id for step in plan.steps]
        captured["smoke_urls"] = {step.id: step.url for step in plan.steps}
        return _successful_session_smoke_results()

    def fake_run_validation_jobs(*, run_id, runtime_workspace, report_root, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        backend_path = report_root / "backend-evaluation.json"
        frontend_path = report_root / "frontend-evaluation.json"
        backend_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        frontend_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        (report_root / "frontend-build-validation.json").write_text(
            json.dumps({"bootstrap_failure_reason": ""}),
            encoding="utf-8",
        )
        return {"backend": backend_path, "frontend": frontend_path}

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._run_validation_evaluation_jobs", fake_run_validation_jobs)

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-session-native",
        agent_version="test-v1",
        onboarding_credentials={"username": "demo", "password": "secret"},
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    manifest = json.loads((generated_root / "food" / "food-run-session-native" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["credentials"] == {"username": "demo", "password": "secret"}
    assert captured["step_ids"] == ["login", "session-me", "product-api", "order-api"]
    assert captured["smoke_urls"]["login"] == "http://127.0.0.1:8000/api/users/login/"
    assert captured["smoke_urls"]["session-me"] == "http://127.0.0.1:8000/api/users/me/"
    assert result["current_state"] == "completed"


def test_run_onboarding_generation_stops_on_structural_failure_without_retry(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        return [
            {
                "step": "smoke-tests/missing.sh",
                "step_id": "missing",
                "returncode": 127,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "",
                "stderr": "Smoke script not found: /tmp/missing.sh",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    role_runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": "Detected onboarding structure",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "plan generation",
                "blocking_issue": "none",
            },
            "Planner": lambda context: {
                "claim": "Generate auth/order/product/front patch",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "generate overlay",
                "blocking_issue": "none",
            },
            "Generator": lambda context: {
                "claim": "Prepare overlay proposal",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "materialize proposal",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": context["proposed_files"],
                    "proposed_patches": context["proposed_patches"],
                },
            },
            "Diagnostician": lambda context: {
                "claim": "Structural failure should not retry",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "high",
                "next_action": "request_human_review",
                "blocking_issue": "missing smoke script",
                "metadata": {
                    "classification": "missing_smoke_script",
                    "should_retry": True,
                    "proposed_fix": "restore missing smoke script",
                    "failure_signature": "missing_smoke_script:missing",
                },
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-structural",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
        },
    )

    assert smoke_calls["count"] == 1
    assert result["current_state"] == "human_review_required"
    assert "frontend_build_validation_path" in result
    assert "recovery_artifact_path" in result


def test_run_onboarding_generation_reports_recovery_artifact_path(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "chat-auth-token",
                "step_id": "chat-auth-token",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "response body shape mismatch",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "HTTP contract mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.83,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "response body is nested",
                "proposed_fix": "override chat-auth-token export path",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-recovery-contract",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    assert result["recovery_artifact_path"] is not None
    assert result["recovery_artifact_path"].endswith("reports/recovery-plan.json")


def test_run_onboarding_generation_persists_repair_history_across_runs(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "chat-auth-token",
                "step_id": "chat-auth-token",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "response body shape mismatch",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "HTTP contract mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.83,
            "risk": "medium",
            "next_action": "request_human_review",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": False,
                "root_cause_hypothesis": "response body is nested",
                "proposed_fix": "override chat-auth-token export path",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    first = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-history-1",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )
    second = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-history-2",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    first_history = json.loads(Path(first["repair_history_path"]).read_text(encoding="utf-8"))
    second_history = json.loads(Path(second["repair_history_path"]).read_text(encoding="utf-8"))
    site_history = json.loads(Path(second["site_repair_history_path"]).read_text(encoding="utf-8"))

    assert first_history["failure_signature"] == "response_schema_mismatch:chat-auth-token"
    assert first_history["failure_count_for_signature"] == 1
    assert second_history["failure_count_for_signature"] == 2
    assert site_history["signatures"]["response_schema_mismatch:chat-auth-token"]["count"] == 2


def test_run_onboarding_generation_promotes_repeated_pipeline_signature(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "frontend-runtime",
                "step_id": "frontend-runtime",
                "required": True,
                "category": "frontend",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "build artifact selected as mount target",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Frontend target selection bug detected",
            "evidence": context["evidence"],
            "confidence": 0.85,
            "risk": "medium",
            "next_action": "request_human_review",
            "blocking_issue": "none",
            "metadata": {
                "classification": "frontend_target_detection",
                "should_retry": False,
                "failure_signature": "frontend_target_detection:build_artifact_selected",
            },
        }
    )

    first = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-promote-1",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )
    second = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-promote-2",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    assert first["repair_scope"] == "run_only"
    assert first["promotion_decision"]["promote"] is False
    assert second["repair_scope"] == "generator_promoted"
    assert second["promotion_decision"]["promote"] is True


def test_run_onboarding_generation_promoted_repair_requires_fresh_run_id(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "frontend-runtime",
                "step_id": "frontend-runtime",
                "required": True,
                "category": "frontend",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "build artifact selected as mount target",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Frontend target selection bug detected",
            "evidence": context["evidence"],
            "confidence": 0.85,
            "risk": "medium",
            "next_action": "request_human_review",
            "blocking_issue": "none",
            "metadata": {
                "classification": "frontend_target_detection",
                "should_retry": False,
                "failure_signature": "frontend_target_detection:build_artifact_selected",
            },
        }
    )

    run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-generator-path-1",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )
    second = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-generator-path-2",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    request_payload = json.loads(Path(second["generator_repair_request_path"]).read_text(encoding="utf-8"))

    assert second["repair_scope"] == "generator_promoted"
    assert request_payload["requires_fresh_run"] is True
    assert request_payload["ownership_root"] == "chatbot/src/onboarding"


def test_run_onboarding_generation_promotes_second_routes_child_violation(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "frontend-runtime",
                "step_id": "frontend-runtime",
                "required": True,
                "category": "frontend",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "routes child violation",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "React Routes child rule violated",
            "evidence": context["evidence"],
            "confidence": 0.82,
            "risk": "medium",
            "next_action": "request_human_review",
            "blocking_issue": "none",
            "metadata": {
                "classification": "frontend_mount_violation",
                "should_retry": False,
                "failure_signature": "frontend_mount_violation:routes_child_violation",
            },
        }
    )

    first = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-routes-child-1",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )
    second = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-routes-child-2",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    assert first["repair_scope"] == "run_only"
    assert second["repair_scope"] == "generator_promoted"
    assert second["promotion_decision"]["promote"] is True


def test_run_onboarding_generation_calls_recovery_planner_for_recoverable_failure(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    planner_calls: list[dict[str, Any]] = []

    def fake_build_recovery_plan(context: dict[str, Any]) -> dict[str, Any]:
        planner_calls.append(context)
        return {
            "classification": "response_schema_mismatch",
            "should_retry": True,
            "proposed_probe_updates": [],
            "proposed_schema_overrides": [],
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_recovery_plan",
        fake_build_recovery_plan,
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "chat-auth-token",
                "step_id": "chat-auth-token",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "response body shape mismatch",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "HTTP contract mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.83,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "response body is nested",
                "proposed_fix": "override chat-auth-token export path",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-recovery-planner",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    assert planner_calls
    assert planner_calls[0]["failure_signature"] == "response_schema_mismatch:chat-auth-token"


def test_run_onboarding_generation_repairs_missing_import_before_human_review(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-runtime-repair" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")
    runtime_workspace.mkdir(parents=True)

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)

    def fake_simulate_runtime_merge(**kwargs):
        path = Path(kwargs["report_root"]) / "merge-simulation.json"
        path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        return path

    monkeypatch.setattr(orchestrator_module, "simulate_runtime_merge", fake_simulate_runtime_merge)

    def fake_validation_jobs(*, run_id: str, runtime_workspace: Path, report_root: Path, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        repaired = (runtime_workspace / "backend" / "chat_auth.py").exists()
        backend_payload = {
            "framework": "django",
            "passed": repaired,
            "route_wiring": {
                "chat_auth_route_detected": repaired,
                "files": ["backend/foodshop/urls.py"] if repaired else [],
                "validation_errors": [] if repaired else ["missing chat auth import target"],
                "detected_registration_point": "backend/foodshop/urls.py",
            },
        }
        frontend_payload = {
            "framework": "react",
            "passed": True,
            "frontend_artifact": {
                "validation_errors": [],
            },
        }
        (report_root / "backend-evaluation.json").write_text(json.dumps(backend_payload), encoding="utf-8")
        (report_root / "frontend-evaluation.json").write_text(json.dumps(frontend_payload), encoding="utf-8")
        (report_root / "frontend-build-validation.json").write_text(json.dumps({}), encoding="utf-8")
        return {
            "backend": report_root / "backend-evaluation.json",
            "frontend": report_root / "frontend-evaluation.json",
        }

    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", fake_validation_jobs)
    monkeypatch.setattr(orchestrator_module, "load_smoke_plan", lambda *_: type("Plan", (), {"steps": []})())
    monkeypatch.setattr(orchestrator_module, "_run_validation_with_retries", lambda **_: _successful_smoke_results())
    monkeypatch.setattr(
        orchestrator_module,
        "export_runtime_patch",
        lambda **kwargs: (Path(kwargs["report_root"]) / "export-metadata.json").write_text(
            json.dumps({"patch_path": "approved.patch"}),
            encoding="utf-8",
        ),
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-runtime-repair",
        agent_version="test-v1",
        role_runner=_build_simple_role_runner(
            lambda context: {
                "claim": "Runtime validation failure is repairable",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "retry_validation",
                "blocking_issue": "none",
                "metadata": {"should_retry": True},
            }
        ),
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    recovery_events = json.loads((Path(result["run_root"]) / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert (runtime_workspace / "backend" / "chat_auth.py").exists()
    assert any(event["component"] == "repair_loop" for event in recovery_events)


def test_run_onboarding_generation_retry_recoverable_mismatch_within_budget(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(**kwargs):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [
                {
                    "step": "chat-auth-token",
                    "step_id": "chat-auth-token",
                    "required": True,
                    "category": "auth",
                    "timed_out": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "response body shape mismatch",
                }
            ]
        return _successful_smoke_results()

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Recoverable mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.8,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "nested token response",
                "proposed_fix": "override token export",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-retry-success",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    attempts = json.loads(Path(result["recovery_attempts_path"]).read_text(encoding="utf-8"))
    assert smoke_calls["count"] == 2
    assert result["current_state"] == "completed"
    assert len(attempts) == 1
    assert attempts[0]["retry_count"] == 1


def test_run_onboarding_generation_retry_stops_on_nonrecoverable_mismatch(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")

    smoke_calls = {"count": 0}
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **kwargs: smoke_calls.__setitem__("count", smoke_calls["count"] + 1) or [
            {
                "step": "login",
                "step_id": "login",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "Smoke script not found: /tmp/missing.sh",
            }
        ],
    )

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Structural mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.91,
            "risk": "high",
            "next_action": "request_human_review",
            "blocking_issue": "missing smoke script",
            "metadata": {
                "classification": "missing_smoke_script",
                "should_retry": False,
                "root_cause_hypothesis": "missing script",
                "proposed_fix": "restore script",
                "failure_signature": "missing_smoke_script:login",
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-retry-stop",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    attempts = json.loads(Path(result["recovery_attempts_path"]).read_text(encoding="utf-8"))
    assert smoke_calls["count"] == 1
    assert result["current_state"] == "human_review_required"
    assert attempts[0]["should_retry"] is False


def test_run_onboarding_generation_retry_stops_on_repeated_identical_signature(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(**kwargs):
        smoke_calls["count"] += 1
        return [
            {
                "step": "chat-auth-token",
                "step_id": "chat-auth-token",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "response body shape mismatch",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Recoverable mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.8,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "nested token response",
                "proposed_fix": "override token export",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-retry-duplicate",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    attempts = json.loads(Path(result["recovery_attempts_path"]).read_text(encoding="utf-8"))
    assert smoke_calls["count"] == 2
    assert result["current_state"] == "human_review_required"
    assert attempts[-1]["stop_reason"] == "duplicate_failure_signature"


def test_run_onboarding_generation_recovery_result_includes_final_recovery_source(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(**kwargs):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [
                {
                    "step": "chat-auth-token",
                    "step_id": "chat-auth-token",
                    "required": True,
                    "category": "auth",
                    "timed_out": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "response body shape mismatch",
                }
            ]
        return _successful_smoke_results()

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Recoverable mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.8,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "nested token response",
                "proposed_fix": "override token export",
                "failure_signature": "response_schema_mismatch:chat-auth-token",
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-recovery-result",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    assert result["recovery_artifact_path"].endswith("reports/recovery-plan.json")
    assert result["final_recovery_source"] == "response_schema_mismatch"


def test_run_onboarding_generation_records_frontend_provenance(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **_: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id="frontend-provenance-001",
            agent_version="test-v1",
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    run_root = generated_root / "food" / "frontend-provenance-001"

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("frontend_artifacts") == []
    patch_content = (run_root / "patches" / "frontend_widget_mount.patch").read_text(encoding="utf-8")
    assert "widget.js" in patch_content
    assert "order-cs-widget" in patch_content
    assert "/api/chat/auth-token" in patch_content
    build_report_path = result.get("frontend_build_validation_path")
    assert build_report_path
    assert Path(build_report_path).exists()


def test_build_run_result_includes_runtime_failure_summary(tmp_path: Path):
    from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator
    from chatbot.src.onboarding.orchestrator import _build_run_result

    run_root = tmp_path / "generated" / "food" / "run-001"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "reports" / "backend-evaluation.json").write_text(
        json.dumps(
            {
                "backend_bootstrap": {
                    "bootstrap_attempted": True,
                    "bootstrap_passed": False,
                    "bootstrap_failure_reason": "pip install failed",
                }
            }
        ),
        encoding="utf-8",
    )
    (run_root / "reports" / "frontend-build-validation.json").write_text(
        json.dumps(
            {
                "bootstrap_failure_stage": "install_environment_failed",
                "bootstrap_failure_reason": "npm install failed",
            }
        ),
        encoding="utf-8",
    )

    result = _build_run_result(
        run_id="run-001",
        run_root=run_root,
        runtime_workspace=None,
        agent=AgentOrchestrator(run_id="run-001"),
        bridge=None,
        event_store=None,
    )

    assert result["runtime_failure_summary"] == {
        "backend": "pip install failed",
        "frontend": "npm install failed",
    }


def test_run_onboarding_generation_can_resume_existing_run_from_validation_checkpoint(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    run_root = generated_root / "food" / "food-run-resume"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )
    (run_root / "reports").mkdir(parents=True)
    (run_root / "patches").mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-resume",
                "site": "food",
                "source_root": str(source_root),
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"framework": {"backend": "django", "frontend": "react"}},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            }
        ),
        encoding="utf-8",
    )
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (run_root / "reports" / "merge-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "frontend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": False, "failure_count": 1}),
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    monkeypatch.setattr(
        orchestrator_module,
        "generate_run_bundle",
        lambda **_: (_ for _ in ()).throw(AssertionError("generate_run_bundle should not run during resume")),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "write_codebase_map",
        lambda **_: (_ for _ in ()).throw(AssertionError("write_codebase_map should not run during resume")),
    )

    runtime_workspace = runtime_root / "food" / "food-run-resume" / "workspace"
    runtime_workspace.mkdir(parents=True)
    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)
    monkeypatch.setattr(
        orchestrator_module,
        "simulate_runtime_merge",
        lambda **kwargs: (run_root / "reports" / "merge-simulation.json"),
    )
    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", lambda **_: None)
    monkeypatch.setattr(orchestrator_module, "load_smoke_plan", lambda *_: type("Plan", (), {"steps": []})())
    monkeypatch.setattr(orchestrator_module, "_run_validation_with_retries", lambda **_: _successful_smoke_results())
    monkeypatch.setattr(orchestrator_module, "summarize_smoke_results", lambda results: {
        "passed": True,
        "total_steps": len(results),
        "failure_count": 0,
        "required_failures": [],
        "optional_failures": [],
        "timed_out_steps": [],
        "missing_scripts": [],
    })
    monkeypatch.setattr(
        orchestrator_module,
        "export_runtime_patch",
        lambda **kwargs: (run_root / "reports" / "export-metadata.json").write_text(
            json.dumps({"patch_path": "approved.patch"}),
            encoding="utf-8",
        ),
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-resume",
        agent_version="test-v1",
        approval_decisions={"export": "approve"},
        resume_from_existing=True,
    )

    assert result["resume_checkpoint"]["resume_from_stage"] == "validation"
    assert result["export_metadata_path"].endswith("reports/export-metadata.json")


def test_run_onboarding_generation_resume_export_stage_creates_and_posts_export_approval(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    approval_root = tmp_path / "approvals"
    run_root = generated_root / "food" / "food-run-export-resume"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )
    (run_root / "reports").mkdir(parents=True)
    (run_root / "patches").mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-export-resume",
                "site": "food",
                "source_root": str(source_root),
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"framework": {"backend": "django", "frontend": "react"}},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            }
        ),
        encoding="utf-8",
    )
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (run_root / "reports" / "merge-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "frontend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": True, "failure_count": 0}),
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    runtime_workspace = runtime_root / "food" / "food-run-export-resume" / "workspace"
    runtime_workspace.mkdir(parents=True)
    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)
    monkeypatch.setattr(
        orchestrator_module,
        "simulate_runtime_merge",
        lambda **kwargs: (run_root / "reports" / "merge-simulation.json"),
    )

    bridge = InMemorySlackBridge(channel="#onboarding")
    approval_store = ApprovalStore(root=approval_root)

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-export-resume",
        agent_version="test-v1",
        slack_bridge=bridge,
        approval_store=approval_store,
        resume_from_existing=True,
    )

    export_request = approval_store.get_decision(
        run_id="food-run-export-resume",
        approval_type="export",
    )
    approval_messages = [
        message
        for message in bridge.messages
        if message["message"].get("kind") == "approval_request"
    ]

    assert result["resume_checkpoint"]["resume_from_stage"] == "export"
    assert result["current_state"] == "awaiting_export_approval"
    assert result["pending_approval"]["approval_type"] == "export"
    assert export_request is not None
    assert export_request["status"] == "pending"
    assert approval_messages
    assert approval_messages[-1]["message"]["approval_type"] == "export"


def test_run_onboarding_generation_skips_slack_approval_requests_when_explicit_decisions_exist(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    def fake_run_validation_jobs(*, run_id, runtime_workspace, report_root, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        backend_path = report_root / "backend-evaluation.json"
        frontend_path = report_root / "frontend-evaluation.json"
        backend_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        frontend_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        (report_root / "frontend-build-validation.json").write_text(
            json.dumps({"bootstrap_failure_reason": ""}),
            encoding="utf-8",
        )
        return {"backend": backend_path, "frontend": frontend_path}

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: _successful_session_smoke_results(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator._run_validation_evaluation_jobs",
        fake_run_validation_jobs,
    )

    bridge = InMemorySlackBridge(channel="#onboarding")

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-slack-auto-approve",
        agent_version="test-v1",
        slack_bridge=bridge,
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    approval_messages = [
        message
        for message in bridge.messages
        if message["message"].get("kind") == "approval_request"
    ]

    assert result["current_state"] == "completed"
    assert approval_messages == []


def test_run_onboarding_generation_emits_structured_smoke_results(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **_: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id="smoke-structure-001",
            agent_version="test-v1",
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    run_root = Path(result["run_root"])
    smoke_results = json.loads((run_root / "reports" / "smoke-results.json").read_text(encoding="utf-8"))
    assert smoke_results
    for step in smoke_results:
        assert "request" in step
        assert "method" in step["request"]
        assert "url" in step["request"]
        assert "response" in step
        assert "status" in step["response"]
        assert "body" in step["response"] or "text" in step["response"] or "json" in step["response"]
        assert "exports" in step or "state" in step


def test_run_onboarding_generation_stops_when_frontend_evaluation_is_invalid(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <div>Home</div>; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    def fake_run_validation_jobs(*, run_id, runtime_workspace, report_root, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        backend_path = report_root / "backend-evaluation.json"
        frontend_path = report_root / "frontend-evaluation.json"
        backend_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        frontend_path.write_text(
            json.dumps(
                {
                    "passed": False,
                    "failure_reason": "frontend mount invalid",
                    "frontend_artifact": {
                        "validation_status": "invalid",
                        "validation_errors": [
                            "mount missing order-cs-widget bundle bootstrap",
                            "mount missing order-cs-widget usage",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        (report_root / "frontend-build-validation.json").write_text(
            json.dumps(
                {
                    "bootstrap_failure_reason": "",
                    "validation_errors": [
                        "mount missing order-cs-widget bundle bootstrap",
                        "mount missing order-cs-widget usage",
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {"backend": backend_path, "frontend": frontend_path}

    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", fake_run_validation_jobs)
    monkeypatch.setattr(orchestrator_module, "run_smoke_tests", lambda **_: _successful_smoke_results())

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-invalid-frontend",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    assert result["current_state"] == "human_review_required"
    assert result["runtime_failure_summary"]["frontend"] == "frontend mount invalid"


def test_runtime_completion_backend_import_resolution_failed_maps_to_repair_actions():
    import_failure = build_recovery_plan(
        {
            "failure_signature": "frontend_import_resolution_failed:Can't resolve @shared-chatbot/ChatbotWidget",
            "retry_count": 0,
            "retry_budget": 2,
        }
    )
    backend_import_failure = build_recovery_plan(
        {
            "failure_signature": "backend_import_resolution_failed:ModuleNotFoundError No module named backend",
            "retry_count": 0,
            "retry_budget": 2,
        }
    )
    mount_failure = build_recovery_plan(
        {
            "failure_signature": "chatbot_mount_missing:mount file missing order-cs-widget",
            "retry_count": 0,
            "retry_budget": 2,
        }
    )
    dev_boot_failure = build_recovery_plan(
        {
            "failure_signature": "frontend_dev_server_boot_failed:react-scripts start exited early",
            "retry_count": 0,
            "retry_budget": 2,
        }
    )

    assert import_failure["classification"] == "frontend_import_resolution_failed"
    assert import_failure["should_retry"] is True
    assert import_failure["repair_actions"][0]["action"] == "repair_frontend_mount_bundle"

    assert backend_import_failure["classification"] == "backend_import_resolution_failed"
    assert backend_import_failure["should_retry"] is True
    assert backend_import_failure["repair_actions"][0]["action"] == "repair_backend_entrypoint"

    assert mount_failure["classification"] == "chatbot_mount_missing"
    assert mount_failure["should_retry"] is True
    assert mount_failure["repair_actions"][0]["action"] == "repair_frontend_mount_target"

    assert dev_boot_failure["classification"] == "frontend_dev_server_boot_failed"
    assert dev_boot_failure["should_retry"] is True
    assert dev_boot_failure["repair_actions"][0]["action"] == "repair_frontend_dev_bootstrap"


def test_apply_repair_actions_repair_backend_entrypoint_rewrites_django_import(tmp_path: Path):
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-backend-import-repair" / "workspace"
    urls_path = runtime_workspace / "backend" / "foodshop" / "urls.py"
    chat_auth_path = runtime_workspace / "backend" / "chat_auth.py"

    urls_path.parent.mkdir(parents=True, exist_ok=True)
    chat_auth_path.parent.mkdir(parents=True, exist_ok=True)
    urls_path.write_text(
        "from backend.chat_auth import chat_auth_token\n"
        "urlpatterns = [chat_auth_token]\n",
        encoding="utf-8",
    )
    chat_auth_path.write_text(
        "def chat_auth_token(request):\n"
        "    return None\n",
        encoding="utf-8",
    )

    applied = orchestrator_module._apply_repair_actions(
        runtime_workspace=runtime_workspace,
        recovery_payload={
            "repair_actions": [
                {
                    "action": "repair_backend_entrypoint",
                    "target_path": "backend",
                }
            ]
        },
        backend_evaluation={"framework": "django"},
        runtime_completion_result={
            "failure_reason": "django_urlconf_import_failed",
            "backend_probe": {
                "stderr": (
                    'Traceback (most recent call last):\n'
                    f'  File "{urls_path}", line 1, in <module>\n'
                    "    from backend.chat_auth import chat_auth_token\n"
                    "ModuleNotFoundError: No module named 'backend'\n"
                )
            },
        },
    )

    assert applied is True
    assert urls_path.read_text(encoding="utf-8").startswith("from chat_auth import chat_auth_token\n")


def test_run_onboarding_generation_runs_runtime_completion_loop_only_when_enabled(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-completion" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)

    def fake_simulate_runtime_merge(**kwargs):
        path = Path(kwargs["report_root"]) / "merge-simulation.json"
        path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        return path

    monkeypatch.setattr(orchestrator_module, "simulate_runtime_merge", fake_simulate_runtime_merge)

    def fake_validation_jobs(*, run_id, runtime_workspace, report_root, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        backend_path = report_root / "backend-evaluation.json"
        frontend_path = report_root / "frontend-evaluation.json"
        backend_path.write_text(json.dumps({"passed": True, "framework": "django"}), encoding="utf-8")
        frontend_path.write_text(json.dumps({"passed": True, "framework": "react"}), encoding="utf-8")
        (report_root / "frontend-build-validation.json").write_text(json.dumps({}), encoding="utf-8")
        return {"backend": backend_path, "frontend": frontend_path}

    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", fake_validation_jobs)
    monkeypatch.setattr(orchestrator_module, "load_smoke_plan", lambda *_: type("Plan", (), {"steps": []})())
    monkeypatch.setattr(orchestrator_module, "_run_validation_with_retries", lambda **_: _successful_smoke_results())

    completion_calls: list[dict[str, object]] = []
    export_calls: list[dict[str, object]] = []

    def fake_run_runtime_completion(**kwargs):
        completion_calls.append(kwargs)
        return {
            "passed": True,
            "failure_reason": None,
            "attempt_count": 1,
            "backend_probe": {"status": "ready"},
            "frontend_probe": {"status": "ready"},
            "mount_probe": {"passed": True},
        }

    def fake_export_runtime_patch(**kwargs):
        export_calls.append(kwargs)
        metadata_path = Path(kwargs["report_root"]) / "export-metadata.json"
        metadata_path.write_text(json.dumps({"patch_path": "approved.patch"}), encoding="utf-8")
        return Path(kwargs["report_root"]) / "approved.patch"

    monkeypatch.setattr(orchestrator_module, "run_runtime_completion", fake_run_runtime_completion)
    monkeypatch.setattr(orchestrator_module, "export_runtime_patch", fake_export_runtime_patch)

    result_without_loop = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-completion-disabled",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    assert result_without_loop["current_state"] == "completed"
    assert completion_calls == []
    assert len(export_calls) == 1

    export_calls.clear()

    result_with_loop = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-completion-enabled",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        enable_runtime_completion_loop=True,
    )

    assert result_with_loop["current_state"] == "completed"
    assert len(completion_calls) == 1
    assert len(export_calls) == 2


def test_run_onboarding_generation_marks_human_review_when_runtime_completion_budget_is_exhausted(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-completion-fail" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)

    def fake_simulate_runtime_merge_failure_case(**kwargs):
        path = Path(kwargs["report_root"]) / "merge-simulation.json"
        path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        return path

    def fake_validation_jobs(*, run_id, runtime_workspace, report_root, event_store):
        report_root.mkdir(parents=True, exist_ok=True)
        backend_path = report_root / "backend-evaluation.json"
        frontend_path = report_root / "frontend-evaluation.json"
        backend_path.write_text(json.dumps({"passed": True, "framework": "django"}), encoding="utf-8")
        frontend_path.write_text(json.dumps({"passed": True, "framework": "react"}), encoding="utf-8")
        (report_root / "frontend-build-validation.json").write_text(json.dumps({}), encoding="utf-8")
        return {"backend": backend_path, "frontend": frontend_path}

    def fake_export_runtime_patch(**kwargs):
        metadata_path = Path(kwargs["report_root"]) / "export-metadata.json"
        metadata_path.write_text(json.dumps({"patch_path": "approved.patch"}), encoding="utf-8")
        return Path(kwargs["report_root"]) / "approved.patch"

    monkeypatch.setattr(orchestrator_module, "simulate_runtime_merge", fake_simulate_runtime_merge_failure_case)
    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", fake_validation_jobs)
    monkeypatch.setattr(orchestrator_module, "load_smoke_plan", lambda *_: type("Plan", (), {"steps": []})())
    monkeypatch.setattr(orchestrator_module, "_run_validation_with_retries", lambda **_: _successful_smoke_results())
    monkeypatch.setattr(
        orchestrator_module,
        "export_runtime_patch",
        fake_export_runtime_patch,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "run_runtime_completion",
        lambda **kwargs: {
            "passed": False,
            "failure_reason": "mount_probe_environment_unsupported",
            "attempt_count": 1,
            "backend_probe": {"status": "ready"},
            "frontend_probe": {"status": "ready"},
            "mount_probe": {"passed": False},
        },
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-completion-fail",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        enable_runtime_completion_loop=True,
    )

    assert result["current_state"] == "human_review_required"


def test_run_onboarding_generation_observability_emits_stage_lifecycle_events(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda *, run_root, runtime_workspace, plan: [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ],
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-observability",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    trace_path = Path(result["onboarding_event_log_path"])
    trace_lines = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    stage_events = {(item["stage"], item["event"]) for item in trace_lines}

    assert result["current_state"] == "completed"
    assert ("analysis", "stage_started") in stage_events
    assert ("analysis", "stage_completed") in stage_events
    assert ("planning", "stage_started") in stage_events
    assert ("planning", "stage_completed") in stage_events
    assert ("generation", "stage_started") in stage_events
    assert ("generation", "stage_completed") in stage_events
    assert ("validation", "stage_started") in stage_events
    assert ("validation", "stage_completed") in stage_events
    assert ("export", "stage_started") in stage_events
    assert ("export", "stage_completed") in stage_events


def test_run_onboarding_generation_result_includes_onboarding_event_log_path(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-observability-path",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    assert result["onboarding_event_log_path"].endswith("reports/execution-trace.jsonl")
    assert Path(result["onboarding_event_log_path"]).exists()


def test_run_onboarding_generation_emits_redis_events(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    run_id = "food-run-redis-events"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")

    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)
    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **kwargs: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id=run_id,
            agent_version="test-v1",
            approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
            event_store=event_store,
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke

    stream = result["run_event_stream"]
    assert stream == f"onboarding:events:{run_id}"
    entries = [json.loads(entry) for entry in fake.lrange(stream, 0, -1)]
    assert entries, "Expected events in the stream"
    assert entries[0]["event"] == "run.created"
    started_roles = {
        entry["payload"]["role"]
        for entry in entries
        if entry["event"] == "job.started"
    }
    completed_roles = {
        entry["payload"]["role"]
        for entry in entries
        if entry["event"] == "job.completed"
    }
    assert {"Analyzer", "Planner", "Generator", "Validator"} <= started_roles
    assert {"Analyzer", "Planner", "Generator", "Validator"} <= completed_roles
    job_ids = {
        entry["payload"]["job_id"]
        for entry in entries
        if entry["event"] == "job.started"
    }
    assert all(
        job_id.startswith(f"{run_id}:") and job_id.count(":") == 2 and job_id.split(":")[-1].isdigit()
        for job_id in job_ids
    )

    completed_job_ids = {
        entry["payload"]["job_id"]
        for entry in entries
        if entry["event"] == "job.completed"
    }
    assert completed_job_ids
    assert completed_job_ids <= job_ids
    assert all(
        job_id.startswith(f"{run_id}:") and job_id.count(":") == 2 and job_id.split(":")[-1].isdigit()
        for job_id in completed_job_ids
    )


def test_run_onboarding_generation_tracks_diagnostician_attempt_job_ids(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    run_id = "food-run-diagnosis-attempts"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)
    from chatbot.src.onboarding import orchestrator as orchestrator_module

    smoke_calls = {"count": 0}
    original_run_smoke_tests = orchestrator_module.run_smoke_tests

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        if smoke_calls["count"] <= 2:
            failure_record = json.loads(json.dumps(_successful_smoke_results()[0]))
            failure_record.update(
                {
                    "step": f"diagnosis-{smoke_calls['count']}",
                    "step_id": f"diagnosis-{smoke_calls['count']}",
                    "returncode": 1,
                    "stderr": "diagnostic failure",
                }
            )
            return [failure_record]
        return _successful_smoke_results()

    orchestrator_module.run_smoke_tests = fake_run_smoke_tests
    role_runner = _build_simple_role_runner(
        lambda context: {
            "claim": "Recoverable mismatch detected",
            "evidence": context["evidence"],
            "confidence": 0.82,
            "risk": "medium",
            "next_action": "retry_validation",
            "blocking_issue": "none",
            "metadata": {
                "classification": "response_schema_mismatch",
                "should_retry": True,
                "root_cause_hypothesis": "response schema drift",
                "proposed_fix": "override exports",
                "failure_signature": f"response_schema_mismatch:{context['failed_steps'][0]}",
            },
        }
    )
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id=run_id,
            agent_version="test-v1",
            approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
            event_store=event_store,
            role_runner=role_runner,
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    stream = result["run_event_stream"]
    entries = [json.loads(entry) for entry in fake.lrange(stream, 0, -1)]
    diagnostician_started = [
        entry
        for entry in entries
        if entry["event"] == "job.started" and entry["payload"]["role"] == "Diagnostician"
    ]
    diagnostician_completed = [
        entry
        for entry in entries
        if entry["event"] == "job.completed" and entry["payload"]["role"] == "Diagnostician"
    ]

    expected_job_ids = [f"{run_id}:Diagnostician:1", f"{run_id}:Diagnostician:2"]
    assert [entry["payload"]["job_id"] for entry in diagnostician_started] == expected_job_ids
    assert [entry["payload"]["job_id"] for entry in diagnostician_completed] == expected_job_ids
    assert not any(
        entry["event"] == "job.failed" and entry["payload"]["role"] == "Diagnostician"
        for entry in entries
    )


def test_diagnostician_failure_emits_job_failed_event(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    run_id = "food-run-diagnose-fail"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)

    def exploding_diagnostician(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("diagnostician crash")

    role_runner = _build_simple_role_runner(exploding_diagnostician)
    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        failure = json.loads(json.dumps(_successful_smoke_results()[0]))
        failure.update({"returncode": 1, "stderr": "diagnostics needed"})
        return [failure]

    orchestrator_module.run_smoke_tests = fake_run_smoke_tests
    try:
        with pytest.raises(RuntimeError):
            run_onboarding_generation(
                site="food",
                source_root=source_root,
                generated_root=generated_root,
                runtime_root=runtime_root,
                run_id=run_id,
                agent_version="test-v1",
                approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
                role_runner=role_runner,
                event_store=event_store,
            )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    stream = f"onboarding:events:{run_id}"
    entries = [json.loads(entry) for entry in fake.lrange(stream, 0, -1)]
    diagnostician_started = [
        entry
        for entry in entries
        if entry["event"] == "job.started" and entry["payload"]["role"] == "Diagnostician"
    ]
    diagnostician_failed = [
        entry
        for entry in entries
        if entry["event"] == "job.failed" and entry["payload"]["role"] == "Diagnostician"
    ]

    assert diagnostician_started
    assert diagnostician_failed
    start_id = diagnostician_started[-1]["payload"]["job_id"]
    fail_id = diagnostician_failed[-1]["payload"]["job_id"]
    assert start_id == fail_id
    assert fail_id == f"{run_id}:Diagnostician:1"


def test_job_failure_emits_job_failed_event(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    run_id = "food-run-job-failure"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)

    class ExplodingPlanner(RoleRunner):
        def __init__(self):
            super().__init__(
                responders={
                    "Analyzer": lambda context: {
                        "claim": "analysis done",
                        "evidence": context["evidence"],
                        "confidence": 0.8,
                        "risk": "medium",
                        "next_action": "plan",
                        "blocking_issue": "none",
                    },
                    "Planner": lambda context: (_ for _ in ()).throw(RuntimeError("boom")),
                }
            )

    role_runner = ExplodingPlanner()

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **kwargs: _successful_smoke_results()
    try:
        with pytest.raises(RuntimeError):
            run_onboarding_generation(
                site="food",
                source_root=source_root,
                generated_root=generated_root,
                runtime_root=runtime_root,
                run_id=run_id,
                agent_version="test-v1",
                role_runner=role_runner,
                event_store=event_store,
            )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    stream = f"onboarding:events:{run_id}"
    entries = [json.loads(entry) for entry in fake.lrange(stream, 0, -1)]
    failed = [entry for entry in entries if entry["event"] == "job.failed"]
    assert failed
    assert failed[-1]["payload"]["role"] == "Planner"
    job_id = failed[-1]["payload"]["job_id"]
    assert job_id.startswith(f"{run_id}:Planner:")
    assert job_id.split(":")[-1].isdigit()
def test_run_event_stream_is_none_without_event_store(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    original_run_smoke_tests = orchestrator_module.run_smoke_tests
    orchestrator_module.run_smoke_tests = lambda **_: _successful_smoke_results()
    try:
        result = run_onboarding_generation(
            site="food",
            source_root=source_root,
            generated_root=generated_root,
            runtime_root=runtime_root,
            run_id="food-run-no-events",
            agent_version="test-v1",
        )
    finally:
        orchestrator_module.run_smoke_tests = original_run_smoke_tests

    assert result["run_event_stream"] is None
