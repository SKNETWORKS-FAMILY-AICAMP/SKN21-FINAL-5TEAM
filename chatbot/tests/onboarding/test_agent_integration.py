import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.orchestrator import run_onboarding_generation
from chatbot.src.onboarding.redis_store import RedisRunJobStore
from chatbot.src.onboarding.role_runner import LLMRoleRunner, RoleRunner
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge


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


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._expiry: dict[str, int] = {}
        self._lock = threading.Lock()

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs: Any) -> None:
        if mapping is None:
            mapping = {}
        with self._lock:
            self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        with self._lock:
            return dict(self._hashes.get(key) or {})

    def sadd(self, key: str, member: str) -> None:
        with self._lock:
            self._sets.setdefault(key, set()).add(member)

    def rpush(self, key: str, value: str) -> None:
        with self._lock:
            self._lists.setdefault(key, []).append(value)

    def lpop(self, key: str) -> str | None:
        with self._lock:
            values = self._lists.get(key, [])
            if not values:
                return None
            return values.pop(0)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        with self._lock:
            values = self._lists.get(key, [])
            if stop < 0:
                stop = len(values) + stop
            stop = min(stop, len(values) - 1)
            if start >= len(values):
                return []
            return list(values[start : stop + 1])

    def expire(self, key: str, ttl_seconds: int) -> None:
        with self._lock:
            self._expiry[key] = ttl_seconds


@pytest.fixture(autouse=True)
def _stub_smoke_runner(monkeypatch):
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: _successful_smoke_results(),
    )


def test_run_onboarding_generation_emits_slack_observable_messages(tmp_path: Path):
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

    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-001",
        agent_version="test-v1",
        slack_bridge=bridge,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    assert result["slack_message_count"] == len(bridge.messages)
    assert len(bridge.messages) >= 4
    assert bridge.messages[0]["message"]["run_id"] == "food-run-001"
    assert any(entry["message"].get("role") == "Analyzer" for entry in bridge.messages)
    assert any(entry["message"].get("role") == "Planner" for entry in bridge.messages)
    assert any(entry["message"].get("role") == "Generator" for entry in bridge.messages)
    assert any(entry["message"].get("approval_type") == "apply" for entry in bridge.messages)
    assert bridge.messages[-1]["message"]["kind"] == "run_summary"
    assert bridge.messages[-1]["message"]["current_state"] == "completed"

    smoke_results = json.loads((generated_root / "food" / "food-run-001" / "reports" / "smoke-results.json").read_text(encoding="utf-8"))
    assert smoke_results[0]["returncode"] == 0


def test_run_onboarding_generation_stops_when_analysis_approval_missing(tmp_path: Path):
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

    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-002",
        agent_version="test-v1",
        slack_bridge=bridge,
        approval_decisions={},
    )

    assert result["current_state"] == "awaiting_analysis_approval"
    assert result["pending_approval"]["approval_type"] == "analysis"
    assert not (generated_root / "food" / "food-run-002" / "reports" / "smoke-results.json").exists()
    assert any(entry["message"].get("approval_type") == "analysis" for entry in bridge.messages)


def test_run_onboarding_generation_uses_approval_store_decisions(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    approval_root = tmp_path / "approvals"

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

    store = ApprovalStore(root=approval_root)
    for approval_type in ["analysis", "apply", "export"]:
        store.create_request(run_id="food-run-store", approval_type=approval_type)
        store.record_decision(
            run_id="food-run-store",
            approval_type=approval_type,
            decision="approve",
            actor="U123",
        )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-store",
        agent_version="test-v1",
        approval_store=store,
    )

    assert result["current_state"] == "completed"
    assert store.get_decision(run_id="food-run-store", approval_type="analysis")["status"] == "consumed"
    assert store.get_decision(run_id="food-run-store", approval_type="apply")["status"] == "consumed"
    assert store.get_decision(run_id="food-run-store", approval_type="export")["status"] == "consumed"


def test_run_onboarding_generation_with_slack_bridge_waits_for_store_decision(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    approval_root = tmp_path / "approvals"

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

    store = ApprovalStore(root=approval_root)
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-pending",
        agent_version="test-v1",
        slack_bridge=bridge,
        approval_store=store,
    )

    decision = store.get_decision(run_id="food-run-pending", approval_type="analysis")
    assert result["current_state"] == "awaiting_analysis_approval"
    assert result["pending_approval"]["approval_type"] == "analysis"
    assert decision is not None
    assert decision["status"] == "pending"
    assert any(entry["message"].get("approval_type") == "analysis" for entry in bridge.messages)
    assert bridge.messages[-1]["message"]["kind"] == "run_summary"


def test_run_onboarding_generation_returns_generation_log_path_and_writes_timeline(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-generation-log",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    log_path = Path(result["generation_log_path"])
    log_text = log_path.read_text(encoding="utf-8")

    assert result["generation_log_path"].endswith("reports/generation.log")
    assert log_path.exists()
    assert "analysis_started" in log_text
    assert "codebase_map_written" in log_text
    assert "patch_proposal_written" in log_text


def test_run_onboarding_generation_generation_log_covers_patch_simulation_smoke_and_export(tmp_path: Path):
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    class FakeLLM:
        def __init__(self, content: str):
            self.content = content

        def invoke(self, messages):
            return type("LLMResponse", (), {"content": self.content})()

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-generation-log-expanded",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        generate_llm_patch_draft=True,
        llm_patch_factory=lambda: FakeLLM(
            """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ malformed
"""
        ),
    )

    log_text = Path(result["generation_log_path"]).read_text(encoding="utf-8")

    assert "llm_patch_draft_started" in log_text
    assert "hard_fallback_used" in log_text
    assert "llm_patch_draft_hard_fallback" in log_text
    assert "llm_patch_simulation_completed" in log_text
    assert "merge_simulation_completed" in log_text
    assert "smoke_tests_completed" in log_text
    assert "export_completed" in log_text


def test_run_onboarding_generation_retries_after_diagnostician_signal(tmp_path: Path, monkeypatch):
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

    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [{"step": "smoke-tests/login.sh", "returncode": 1, "stdout": "", "stderr": "boom"}]
        return [{"step": "smoke-tests/login.sh", "returncode": 0, "stdout": "ok", "stderr": ""}]

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
            "Validator": lambda context: {
                "claim": "Validation failed" if not context["passed"] else "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "high" if not context["passed"] else "low",
                "next_action": "send to diagnostician" if not context["passed"] else "request export approval",
                "blocking_issue": "smoke failure" if not context["passed"] else "none",
            },
            "Diagnostician": lambda context: {
                "claim": "Failure looks transient, retry validation once",
                "evidence": context["evidence"],
                "confidence": 0.77,
                "risk": "medium",
                "next_action": "retry_validation",
                "blocking_issue": "none",
                "metadata": {"should_retry": True},
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-003",
        agent_version="test-v1",
        slack_bridge=bridge,
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    assert smoke_calls["count"] == 2
    assert result["current_state"] == "completed"
    assert any(entry["message"].get("role") == "Diagnostician" for entry in bridge.messages)


def test_run_onboarding_generation_runtime_repair_emits_repair_loop_event(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-runtime-repair" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text("function App() { return <Chatbot />; }\n", encoding="utf-8")
    runtime_workspace.mkdir(parents=True)

    bridge = InMemorySlackBridge(channel="#onboarding-runs")

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
        (report_root / "backend-evaluation.json").write_text(
            json.dumps(
                {
                    "framework": "django",
                    "passed": repaired,
                    "route_wiring": {
                        "validation_errors": [] if repaired else ["missing chat auth import target"],
                        "detected_registration_point": "backend/foodshop/urls.py",
                    },
                }
            ),
            encoding="utf-8",
        )
        (report_root / "frontend-evaluation.json").write_text(
            json.dumps({"framework": "react", "passed": True, "frontend_artifact": {"validation_errors": []}}),
            encoding="utf-8",
        )
        (report_root / "frontend-build-validation.json").write_text(json.dumps({}), encoding="utf-8")
        return {
            "backend": report_root / "backend-evaluation.json",
            "frontend": report_root / "frontend-evaluation.json",
        }

    monkeypatch.setattr(orchestrator_module, "_run_validation_evaluation_jobs", fake_validation_jobs)
    monkeypatch.setattr(orchestrator_module, "load_smoke_plan", lambda *_: type("Plan", (), {"steps": []})())
    monkeypatch.setattr(orchestrator_module, "_run_validation_with_retries", lambda **_: _successful_smoke_results())
    export_calls: list[dict[str, object]] = []

    def fake_export_runtime_patch(**kwargs):
        export_calls.append(kwargs)
        return (Path(kwargs["report_root"]) / "export-metadata.json").write_text(
            json.dumps({"patch_path": "approved.patch"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        orchestrator_module,
        "export_runtime_patch",
        fake_export_runtime_patch,
    )

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
            "Validator": lambda context: {
                "claim": "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low",
                "next_action": "request export approval",
                "blocking_issue": "none",
            },
            "Diagnostician": lambda context: {
                "claim": "Repair runtime validation before human review",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "retry_validation",
                "blocking_issue": "none",
                "metadata": {"should_retry": True},
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-runtime-repair",
        agent_version="test-v1",
        slack_bridge=bridge,
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    recovery_events = json.loads((Path(result["run_root"]) / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert any(event["component"] == "repair_loop" for event in recovery_events)
    assert export_calls
    assert export_calls[0]["strategy_provenance"]["backend_strategy"] in {"django", "unknown"}
    assert export_calls[0]["strategy_provenance"]["frontend_strategy"] == "react"
    assert export_calls[0]["recovery_provenance"]["final_recovery_source"] == "missing_import_target"


def test_run_onboarding_generation_writes_diagnostic_report_for_structural_failure(tmp_path: Path, monkeypatch):
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

    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
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
                "metadata": {"should_retry": False},
            },
        }
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-004",
        agent_version="test-v1",
        slack_bridge=bridge,
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-004"
    diagnostic_report = json.loads((run_root / "reports" / "diagnostic-report.json").read_text(encoding="utf-8"))

    assert result["current_state"] == "human_review_required"
    assert diagnostic_report["final_action"] == "request_human_review"
    assert diagnostic_report["failure_signature"] == "missing:127"
    assert diagnostic_report["retryable"] is False
    assert any(
        entry["message"].get("role") == "Diagnostician"
        and "retryable: False" in entry["message"].get("evidence", [])
        for entry in bridge.messages
    )


def test_run_onboarding_generation_passes_rich_analysis_context_to_roles(tmp_path: Path):
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

    captured: dict[str, list[dict]] = {"Analyzer": [], "Planner": [], "Generator": []}

    role_runner = RoleRunner(
        responders={
            "Analyzer": lambda context: captured["Analyzer"].append(context) or {
                "claim": "Detected onboarding structure",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "plan generation",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Planner": lambda context: captured["Planner"].append(context) or {
                "claim": "Prioritize auth and order outputs",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "generate overlay",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Generator": lambda context: captured["Generator"].append(context) or {
                "claim": "Prepare auth and frontend patch proposals",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "materialize template files",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": context["proposed_files"],
                    "proposed_patches": context["proposed_patches"],
                },
            },
            "Validator": lambda context: {
                "claim": "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low",
                "next_action": "request export approval",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Diagnostician": lambda context: {
                "claim": "No retry needed",
                "evidence": context["evidence"],
                "confidence": 0.7,
                "risk": "low",
                "next_action": "stop",
                "blocking_issue": "none",
                "metadata": {"should_retry": False},
            },
        }
    )

    run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-004",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    analyzer_context = captured["Analyzer"][0]
    planner_context = captured["Planner"][0]
    generator_context = captured["Generator"][0]

    assert analyzer_context["analysis"]["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]
    assert analyzer_context["analysis"]["auth"]["me_entrypoints"] == ["backend/users/views.py:me"]
    assert analyzer_context["analysis"]["product_api"] == ["/api/products/"]
    assert analyzer_context["analysis"]["order_api"] == ["/api/orders/"]
    assert analyzer_context["analysis"]["frontend_mount_points"] == ["frontend/src/App.js"]
    assert any("backend/users/views.py:login" in item for item in analyzer_context["evidence"])
    assert any("백엔드 프레임워크: django" in item for item in analyzer_context["evidence"])
    assert any("인증 방식: unknown" in item for item in analyzer_context["evidence"])
    assert planner_context["analysis"]["product_api"] == ["/api/products/"]
    assert planner_context["recommended_outputs"] == [
        "chat_auth",
        "order_adapter",
        "product_adapter",
        "frontend_patch",
    ]
    assert any("권장 산출물: ['chat_auth', 'order_adapter', 'product_adapter', 'frontend_patch']" in item for item in planner_context["evidence"])
    assert any("라우트 프리픽스: []" in item for item in planner_context["evidence"])
    assert generator_context["recommended_outputs"] == [
        "chat_auth",
        "order_adapter",
        "product_adapter",
        "frontend_patch",
    ]
    assert generator_context["proposed_files"] == [
        "files/backend/chat_auth.py",
        "files/backend/order_adapter_client.py",
        "files/backend/product_adapter_client.py",
        "files/frontend/src/chatbot/SharedChatbotWidget.jsx",
        "files/backend/tool_registry.py",
    ]
    assert generator_context["proposed_patches"] == [
        "patches/backend_chat_auth_route.patch",
        "patches/frontend_widget_mount.patch",
    ]


def test_run_onboarding_generation_passes_rich_validation_and_diagnosis_context(tmp_path: Path, monkeypatch):
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

    captured: dict[str, list[dict]] = {"Validator": [], "Diagnostician": []}
    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [{"step": "smoke-tests/order_api.sh", "returncode": 1, "stdout": "", "stderr": "boom"}]
        return [{"step": "smoke-tests/order_api.sh", "returncode": 0, "stdout": "ok", "stderr": ""}]

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
                "metadata": {},
            },
            "Planner": lambda context: {
                "claim": "Generate overlay",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "generate overlay",
                "blocking_issue": "none",
                "metadata": {},
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
            "Validator": lambda context: captured["Validator"].append(context) or {
                "claim": "Validation failed" if not context["passed"] else "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "high" if not context["passed"] else "low",
                "next_action": "send to diagnostician" if not context["passed"] else "request export approval",
                "blocking_issue": "smoke failure" if not context["passed"] else "none",
                "metadata": {},
            },
            "Diagnostician": lambda context: captured["Diagnostician"].append(context) or {
                "claim": "Retry once",
                "evidence": context["evidence"],
                "confidence": 0.77,
                "risk": "medium",
                "next_action": "retry_validation",
                "blocking_issue": "none",
                "metadata": {"should_retry": True},
            },
        }
    )

    run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-005",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    validator_context = captured["Validator"][-1]
    diagnostician_context = captured["Diagnostician"][0]

    assert validator_context["smoke_results"][0]["step"] == "smoke-tests/order_api.sh"
    assert validator_context["smoke_results"][0]["returncode"] == 0
    assert validator_context["failure_count"] == 0
    assert diagnostician_context["failure_signature"] == "smoke-tests/order_api.sh:1"
    assert diagnostician_context["retry_count"] == 1
    assert diagnostician_context["retry_budget"] == 3


def test_run_onboarding_generation_materializes_only_generator_proposals(tmp_path: Path):
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

    role_runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": "Detected onboarding structure",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "plan generation",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Planner": lambda context: {
                "claim": "Prefer auth plus frontend only",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "generate overlay subset",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Generator": lambda context: {
                "claim": "Only auth file and frontend patch are needed",
                "evidence": context["evidence"],
                "confidence": 0.83,
                "risk": "medium",
                "next_action": "materialize subset",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": ["files/backend/chat_auth.py"],
                    "proposed_patches": ["patches/frontend_widget_mount.patch"],
                },
            },
            "Validator": lambda context: {
                "claim": "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low",
                "next_action": "request export approval",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Diagnostician": lambda context: {
                "claim": "No retry needed",
                "evidence": context["evidence"],
                "confidence": 0.7,
                "risk": "low",
                "next_action": "stop",
                "blocking_issue": "none",
                "metadata": {"should_retry": False},
            },
        }
    )

    run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-006",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-006"
    assert (run_root / "files" / "backend" / "chat_auth.py").exists()
    assert not (run_root / "files" / "backend" / "order_adapter_client.py").exists()
    assert not (run_root / "files" / "backend" / "product_adapter_client.py").exists()
    assert (run_root / "patches" / "frontend_widget_mount.patch").exists()


def test_run_onboarding_generation_writes_codebase_map_artifact(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-map",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-map"
    codebase_map_path = run_root / "reports" / "codebase-map.json"
    payload = json.loads(codebase_map_path.read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert codebase_map_path.exists()
    assert "backend/users/views.py" in payload["files"]
    assert any(target["path"] == "backend/users/views.py" for target in payload["candidate_edit_targets"])
    assert any(target["reason"] for target in payload["candidate_edit_targets"])
    assert payload["auth_candidates"]
    assert any(item["path"] == "backend/users/views.py" for item in payload["auth_candidates"])
    assert payload["urlconf_candidates"]
    assert payload["frontend_component_candidates"]


def test_run_onboarding_generation_writes_patch_proposal_artifact(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "backend" / "foodshop").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    session_token = request.COOKIES.get('session_token')\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "users" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = [\n    path('login/', login),\n]\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = [\n    path('', product_list),\n]\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = [\n    path('', order_list),\n]\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "foodshop" / "urls.py").write_text(
        "from django.urls import include, path\n\nurlpatterns = [\n    path('users/', include('users.urls')),\n]\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-proposal",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-proposal"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    payload = json.loads(proposal_path.read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert proposal_path.exists()
    assert payload["target_files"]
    assert payload["target_files"][0]["path"]
    assert payload["target_files"][0]["intent"]
    assert payload["supporting_generated_files"]
    assert any(target["path"] == "backend/users/views.py" for target in payload["target_files"])
    assert any(target["path"] == "backend/foodshop/urls.py" for target in payload["target_files"])
    assert not any(target["path"] == "backend/products/urls.py" for target in payload["target_files"])


def test_run_onboarding_generation_writes_llm_patch_draft_artifact_when_enabled(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "backend" / "foodshop").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "foodshop" / "urls.py").write_text(
        "from django.urls import include, path\n\nurlpatterns = []\n",
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    class FakeLLM:
        def __init__(self, content: str):
            self.content = content
            self.calls: list[list[Any]] = []

        def invoke(self, messages):
            self.calls.append(messages)
            return type("LLMResponse", (), {"content": self.content})()

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
"""
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-llm-patch",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        generate_llm_patch_draft=True,
        llm_patch_factory=lambda: fake_llm,
    )

    run_root = generated_root / "food" / "food-run-llm-patch"
    patch_path = run_root / "patches" / "llm-proposed.patch"
    comparison_path = run_root / "reports" / "patch-comparison.json"
    llm_simulation_path = run_root / "reports" / "llm-patch-simulation.json"
    content = patch_path.read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert result["llm_proposed_patch_path"].endswith("patches/llm-proposed.patch")
    assert result["llm_patch_simulation_path"].endswith("reports/llm-patch-simulation.json")
    assert result["patch_comparison_path"].endswith("reports/patch-comparison.json")
    assert patch_path.exists()
    assert llm_simulation_path.exists()
    assert comparison_path.exists()
    assert "+++ b/backend/users/views.py" in content
    assert "onboarding_chat_auth_token" in content


def test_run_onboarding_generation_recovery_writes_llm_role_execution_report_and_generation_log(tmp_path: Path, monkeypatch):
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

    class FlakyLLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return type(
                    "LLMResponse",
                    (),
                    {
                        "content": json.dumps(
                            {
                                "claim": "llm ok",
                                "evidence": "e1",
                                "confidence": "0.9",
                                "risk": "LOW",
                                "next_action": "continue",
                                "blocking_issue": None,
                                "metadata": None,
                            }
                        )
                    },
                )()
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "claim": "llm ok",
                            "evidence": ["e1"],
                            "confidence": 0.9,
                            "risk": "low",
                            "next_action": "continue",
                            "blocking_issue": "none",
                            "metadata": {},
                        }
                    )
                },
            )()

    flaky_llm = FlakyLLM()

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_llm_role_runner",
        lambda provider, model: LLMRoleRunner(llm_factory=lambda: flaky_llm),
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-llm-roles",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        use_llm_roles=True,
        generate_llm_patch_draft=True,
        llm_patch_factory=lambda: type(
            "BrokenPatchLLM",
            (),
            {
                "invoke": lambda self, messages: type(
                    "LLMResponse",
                    (),
                    {
                        "content": "--- a/backend/users/views.py\n+++ b/backend/users/views.py\n@@ malformed\n",
                    },
                )()
            },
        )(),
    )

    report_path = generated_root / "food" / "food-run-llm-roles" / "reports" / "llm-role-execution.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    log_text = (
        generated_root / "food" / "food-run-llm-roles" / "reports" / "generation.log"
    ).read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert result["llm_role_execution_path"].endswith("reports/llm-role-execution.json")
    assert result["llm_codebase_interpretation_path"].endswith("reports/llm-codebase-interpretation.json")
    assert result["llm_patch_proposal_execution_path"].endswith("reports/llm-patch-proposal-execution.json")
    assert report_path.exists()
    assert payload["roles"]["Analyzer"]["source"] == "recovered_llm"
    assert payload["roles"]["Analyzer"]["recovery_reason"] == "agent_payload_normalized"
    assert payload["roles"]["Planner"]["source"] == "llm"
    proposal_execution = json.loads(
        (
            generated_root / "food" / "food-run-llm-roles" / "reports" / "llm-patch-proposal-execution.json"
        ).read_text(encoding="utf-8")
    )
    codebase_interpretation = json.loads(
        (
            generated_root / "food" / "food-run-llm-roles" / "reports" / "llm-codebase-interpretation.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_execution["source"] in {"llm", "recovered_llm", "hard_fallback"}
    assert codebase_interpretation["source"] in {"llm", "recovered_llm", "hard_fallback"}
    assert "recovery_started" in log_text
    assert "recovery_succeeded" in log_text
    assert "hard_fallback_used" in log_text


def test_run_onboarding_generation_exports_llm_patch_when_recommended(tmp_path: Path, monkeypatch):
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
    (source_root / "backend" / "users" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    class FakeLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,4 +1,7 @@
 def login(request):
     return None
 
 def me(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
"""
                },
            )()

    def write_llm_recommended_report(*, run_root, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "deterministic_patch": {"exists": True, "path": str(Path(run_root) / "patches" / "proposed.patch")},
                    "llm_patch": {"exists": True, "path": str(Path(run_root) / "patches" / "llm-proposed.patch")},
                    "same_content": False,
                    "line_count_delta": 2,
                    "target_file_delta": {"only_in_deterministic": [], "only_in_llm": []},
                    "simulation": {"deterministic_passed": True, "llm_passed": True},
                    "recommended_source": "llm",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.write_patch_comparison_report",
        write_llm_recommended_report,
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-llm-export",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        generate_llm_patch_draft=True,
        llm_patch_factory=lambda: FakeLLM(),
    )

    run_root = generated_root / "food" / "food-run-llm-export"
    export_metadata = json.loads((run_root / "reports" / "export-metadata.json").read_text(encoding="utf-8"))
    approved_patch = (run_root / "reports" / "approved.patch").read_text(encoding="utf-8")
    llm_patch = (run_root / "patches" / "llm-proposed.patch").read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert export_metadata["export_source"] == "llm"
    assert export_metadata["source_patch_path"].endswith("patches/llm-proposed.patch")
    assert approved_patch == llm_patch


def test_run_onboarding_generation_runtime_completion_repairs_runtime_workspace_and_reexports(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-runtime-completion" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    source_app = source_root / "frontend" / "src" / "App.js"
    source_app.write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")

    runtime_app = runtime_workspace / "frontend" / "src" / "App.js"
    runtime_app.parent.mkdir(parents=True, exist_ok=True)
    runtime_app.write_text(source_app.read_text(encoding="utf-8"), encoding="utf-8")

    from chatbot.src.onboarding import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "prepare_runtime_workspace", lambda **_: runtime_workspace)

    def fake_simulate_runtime_merge(**kwargs):
        path = Path(kwargs["report_root"]) / "merge-simulation.json"
        path.write_text(json.dumps({"passed": True}), encoding="utf-8")
        return path

    monkeypatch.setattr(orchestrator_module, "simulate_runtime_merge", fake_simulate_runtime_merge)

    def fake_validation_jobs(*, run_id: str, runtime_workspace: Path, report_root: Path, event_store):
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

    completion_attempts = iter(
        [
            {
                "passed": False,
                "failure_reason": "chatbot_mount_missing",
                "attempt_count": 1,
                "backend_probe": {"status": "ready"},
                "frontend_probe": {"status": "ready"},
                "mount_probe": {"passed": False},
            },
            {
                "passed": True,
                "failure_reason": None,
                "attempt_count": 1,
                "backend_probe": {"status": "ready"},
                "frontend_probe": {"status": "ready"},
                "mount_probe": {"passed": True},
            },
        ]
    )
    monkeypatch.setattr(orchestrator_module, "run_runtime_completion", lambda **kwargs: next(completion_attempts))

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-runtime-completion",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        enable_runtime_completion_loop=True,
    )

    export_metadata = json.loads((Path(result["run_root"]) / "reports" / "export-metadata.json").read_text(encoding="utf-8"))
    approved_patch = (Path(result["run_root"]) / "reports" / "approved.patch").read_text(encoding="utf-8")
    attempts_payload = json.loads((Path(result["run_root"]) / "reports" / "runtime-completion-attempts.json").read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert source_app.read_text(encoding="utf-8") == "export default function App() { return <main>Home</main>; }\n"
    assert "SharedChatbotWidget" in runtime_app.read_text(encoding="utf-8")
    assert "frontend/src/App.js" in export_metadata["changed_files"]
    assert "SharedChatbotWidget" in approved_patch
    assert attempts_payload[-1]["passed"] is True
    assert attempts_payload[0]["classification"] == "chatbot_mount_missing"


def test_run_onboarding_generation_runtime_completion_repairs_shared_widget_import_failure(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-runtime-import-repair" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    widget_path = runtime_workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx"
    widget_path.parent.mkdir(parents=True, exist_ok=True)
    widget_path.write_text(
        '// preserve @shared-chatbot/ChatbotWidget alias comment\n'
        'import { HostedChatbotWidget } from "@shared-chatbot/ChatbotWidget";\n'
        "export default function SharedChatbotWidget() {\n"
        "  return <HostedChatbotWidget />;\n"
        "}\n",
        encoding="utf-8",
    )
    runtime_app = runtime_workspace / "frontend" / "src" / "App.js"
    runtime_app.parent.mkdir(parents=True, exist_ok=True)
    runtime_app.write_text(
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

    def fake_validation_jobs(*, run_id: str, runtime_workspace: Path, report_root: Path, event_store):
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

    completion_attempts = iter(
        [
            {
                "passed": False,
                "failure_reason": "frontend_import_resolution_failed",
                "attempt_count": 1,
                "backend_probe": {"status": "ready"},
                "frontend_probe": {"status": "boot_failed"},
                "mount_probe": {"passed": False},
            },
            {
                "passed": True,
                "failure_reason": None,
                "attempt_count": 1,
                "backend_probe": {"status": "ready"},
                "frontend_probe": {"status": "ready"},
                "mount_probe": {"passed": True},
            },
        ]
    )
    monkeypatch.setattr(orchestrator_module, "run_runtime_completion", lambda **kwargs: next(completion_attempts))

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-runtime-import-repair",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        enable_runtime_completion_loop=True,
    )

    vendored_widget = runtime_workspace / "frontend" / "src" / "chatbot" / "ChatbotWidget.jsx"
    attempts_payload = json.loads((Path(result["run_root"]) / "reports" / "runtime-completion-attempts.json").read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert 'from "./ChatbotWidget"' in widget_path.read_text(encoding="utf-8")
    assert "// preserve @shared-chatbot/ChatbotWidget alias comment" in widget_path.read_text(encoding="utf-8")
    assert vendored_widget.exists()
    assert "HostedChatbotWidget" in vendored_widget.read_text(encoding="utf-8")
    assert attempts_payload[0]["classification"] == "frontend_import_resolution_failed"


def test_run_onboarding_generation_runtime_completion_backend_import_repair(
    tmp_path: Path, monkeypatch
):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    runtime_workspace = runtime_root / "food" / "food-run-runtime-backend-import-repair" / "workspace"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

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
    runtime_app = runtime_workspace / "frontend" / "src" / "App.js"
    runtime_app.parent.mkdir(parents=True, exist_ok=True)
    runtime_app.write_text(
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

    def fake_validation_jobs(*, run_id: str, runtime_workspace: Path, report_root: Path, event_store):
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

    completion_attempts = iter(
        [
            {
                "passed": False,
                "failure_reason": "backend_import_resolution_failed",
                "attempt_count": 1,
                "backend_probe": {
                    "status": "boot_failed",
                    "stderr": (
                        'Traceback (most recent call last):\n'
                        f'  File "{urls_path}", line 1, in <module>\n'
                        "    from backend.chat_auth import chat_auth_token\n"
                        "ModuleNotFoundError: No module named 'backend'\n"
                    ),
                },
                "frontend_probe": {"status": "ready"},
                "mount_probe": {"passed": False},
            },
            {
                "passed": True,
                "failure_reason": None,
                "attempt_count": 1,
                "backend_probe": {"status": "ready"},
                "frontend_probe": {"status": "ready"},
                "mount_probe": {"passed": True},
            },
        ]
    )
    monkeypatch.setattr(orchestrator_module, "run_runtime_completion", lambda **kwargs: next(completion_attempts))
    monkeypatch.setattr(
        orchestrator_module,
        "_apply_repair_actions",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("canned repair should not run before llm repair")),
    )

    class FakeLLM:
        def invoke(self, messages):
            return type(
                "Response",
                (),
                {
                    "content": (
                        "--- a/backend/foodshop/urls.py\n"
                        "+++ b/backend/foodshop/urls.py\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-from backend.chat_auth import chat_auth_token\n"
                        "+from chat_auth import chat_auth_token\n"
                        " urlpatterns = [chat_auth_token]\n"
                    )
                },
            )()

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-runtime-backend-import-repair",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        enable_runtime_completion_loop=True,
        llm_patch_factory=lambda: FakeLLM(),
        generate_llm_patch_draft=True,
    )

    attempts_payload = json.loads((Path(result["run_root"]) / "reports" / "runtime-completion-attempts.json").read_text(encoding="utf-8"))
    approved_patch = (Path(result["run_root"]) / "reports" / "approved.patch").read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert urls_path.read_text(encoding="utf-8").startswith("from chat_auth import chat_auth_token\n")
    assert attempts_payload[0]["classification"] == "backend_import_resolution_failed"
    assert attempts_payload[0]["llm_repair_applied"] is True
    assert attempts_payload[-1]["passed"] is True
    assert "from chat_auth import chat_auth_token" in approved_patch


def test_run_onboarding_generation_writes_debug_trace_and_file_activity(tmp_path: Path):
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
    (source_root / "backend" / "users" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-debug-trace",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-debug-trace"
    trace_path = run_root / "reports" / "execution-trace.jsonl"
    file_activity_path = run_root / "reports" / "file-activity.json"

    assert result["current_state"] == "completed"
    assert trace_path.exists()
    assert file_activity_path.exists()

    trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    file_activity = json.loads(file_activity_path.read_text(encoding="utf-8"))

    assert any(item["event"] == "patch_proposal_written" for item in trace_lines)
    assert "backend/users/views.py" in file_activity
    assert "patch_proposal" in file_activity["backend/users/views.py"]["selected_by"]


def test_run_onboarding_generation_returns_onboarding_event_log_with_stage_lifecycle(tmp_path: Path, monkeypatch):
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
        run_id="food-run-onboarding-events",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    trace_path = Path(result["onboarding_event_log_path"])
    trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lifecycle = {(item["stage"], item["event"]) for item in trace_lines}

    assert trace_path.exists()
    assert ("analysis", "stage_started") in lifecycle
    assert ("export", "stage_completed") in lifecycle


def test_run_onboarding_generation_writes_llm_usage_report(tmp_path: Path, monkeypatch):
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
    (source_root / "backend" / "users" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    class UsageLLM:
        def __init__(self, content: str, usage_metadata: dict[str, int]):
            self.content = content
            self.usage_metadata = usage_metadata

        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": self.content,
                    "usage_metadata": self.usage_metadata,
                    "response_metadata": {
                        "token_usage": {
                            "prompt_tokens": self.usage_metadata.get("input_tokens", 0),
                            "completion_tokens": self.usage_metadata.get("output_tokens", 0),
                            "total_tokens": self.usage_metadata.get("total_tokens", 0),
                            "prompt_tokens_details": {
                                "cached_tokens": self.usage_metadata.get("cached_input_tokens", 0),
                            },
                        }
                    },
                },
            )()

    role_responses = iter(
        [
            UsageLLM(
                json.dumps(
                    {
                        "claim": "analysis ok",
                        "evidence": ["e1"],
                        "confidence": 0.8,
                        "risk": ["Medium", "csrf review"],
                        "next_action": ["plan next"],
                        "blocking_issue": None,
                        "metadata": {},
                    }
                ),
                {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 2, "total_tokens": 15},
            ),
            UsageLLM(
                json.dumps(
                    {
                        "claim": "plan ok",
                        "evidence": ["e1"],
                        "confidence": 0.8,
                        "risk": "medium",
                        "next_action": "generate",
                        "blocking_issue": "none",
                        "metadata": {},
                    }
                ),
                {"input_tokens": 11, "output_tokens": 6, "cached_input_tokens": 1, "total_tokens": 17},
            ),
            UsageLLM(
                json.dumps(
                    {
                        "claim": "generate ok",
                        "evidence": ["e1"],
                        "confidence": 0.8,
                        "risk": "medium",
                        "next_action": "apply",
                        "blocking_issue": "none",
                        "metadata": {
                            "proposed_files": [
                                "files/backend/chat_auth.py",
                                "files/backend/order_adapter_client.py",
                                "files/backend/product_adapter_client.py",
                            ],
                            "proposed_patches": ["patches/frontend_widget_mount.patch"],
                        },
                    }
                ),
                {"input_tokens": 12, "output_tokens": 7, "cached_input_tokens": 3, "total_tokens": 19},
            ),
            UsageLLM(
                json.dumps(
                    {
                        "claim": "validation ok",
                        "evidence": ["e1"],
                        "confidence": 0.8,
                        "risk": "low",
                        "next_action": "export",
                        "blocking_issue": "none",
                        "metadata": {},
                    }
                ),
                {"input_tokens": 13, "output_tokens": 8, "cached_input_tokens": 4, "total_tokens": 21},
            ),
        ]
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_llm_role_runner",
        lambda provider, model: LLMRoleRunner(llm_factory=lambda: next(role_responses), provider=provider, model=model),
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_llm_codebase_interpretation_factory",
        lambda provider, model: (
            lambda: UsageLLM(
                json.dumps(
                    {
                        "structure_summary": "django/react",
                        "framework_assessment": {"backend": "django", "frontend": "react"},
                        "ranked_candidates": [
                            {"path": "backend/users/views.py", "reason": "auth handler"},
                        ],
                    }
                ),
                {"input_tokens": 20, "output_tokens": 10, "cached_input_tokens": 5, "total_tokens": 30},
            )
        ),
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_llm_patch_proposal_factory",
        lambda provider, model: (
            lambda: UsageLLM(
                json.dumps(
                    {
                        "target_files": [
                            {
                                "path": "backend/users/views.py",
                                "reason": "auth handler",
                                "intent": "add onboarding handler",
                            },
                            {
                                "path": "backend/users/urls.py",
                                "reason": "urlconf",
                                "intent": "register onboarding route",
                            },
                            {
                                "path": "frontend/src/App.js",
                                "reason": "frontend app shell",
                                "intent": "mount chatbot widget",
                            },
                        ],
                        "supporting_generated_files": [
                            "backend/chat_auth.py",
                            "backend/adapters/order_adapter.py",
                            "backend/adapters/product_adapter.py",
                        ],
                        "recommended_outputs": [
                            "chat_auth",
                            "order_adapter",
                            "product_adapter",
                            "frontend_patch",
                        ],
                        "analysis_summary": {
                            "auth_style": "session_cookie",
                            "frontend_mount_points": ["frontend/src/App.js"],
                            "route_prefixes": [],
                        },
                    }
                ),
                {"input_tokens": 21, "output_tokens": 11, "cached_input_tokens": 6, "total_tokens": 32},
            )
        ),
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.build_llm_patch_factory",
        lambda provider, model: (
            lambda: UsageLLM(
                """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,4 +1,7 @@
 def login(request):
     return None
 
 def me(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
""",
                {"input_tokens": 22, "output_tokens": 12, "cached_input_tokens": 7, "total_tokens": 34},
            )
        ),
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-llm-usage",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        use_llm_roles=True,
        generate_llm_patch_draft=True,
    )

    run_root = generated_root / "food" / "food-run-llm-usage"
    usage_path = run_root / "reports" / "llm-usage.json"
    payload = json.loads(usage_path.read_text(encoding="utf-8"))

    assert result["current_state"] == "completed"
    assert usage_path.exists()
    assert payload["totals"]["input_tokens"] == 109
    assert payload["totals"]["output_tokens"] == 59
    assert payload["totals"]["cached_input_tokens"] == 28
    components = {item["component"] for item in payload["calls"]}
    assert "role:Analyzer" in components
    assert "role:Planner" in components
    assert "role:Generator" in components
    assert "llm_codebase_interpretation" in components
    assert "llm_patch_proposal" in components
    assert "llm_patch_draft" in components


def test_run_onboarding_generation_emits_terminal_trace_messages(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    messages: list[str] = []

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "users" / "urls.py").write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
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
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-terminal-logs",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
        terminal_logger=messages.append,
    )

    assert result["current_state"] == "completed"
    assert any("[analysis] started site=food" in line for line in messages)
    assert any("[patch_proposal] file=backend/users/views.py" in line for line in messages)
    assert any("reason=backend route or handler candidate" in line for line in messages)


def test_run_onboarding_generation_writes_unified_diff_draft(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-diff",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-diff"
    patch_path = run_root / "patches" / "proposed.patch"
    content = patch_path.read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert result["proposed_patch_path"].endswith("patches/proposed.patch")
    assert patch_path.exists()
    assert "--- a/" in content
    assert "+++ b/" in content
    assert "+++ b/backend/users/views.py" in content
    assert "def onboarding_chat_auth_token(request):" in content
    assert "+++ b/backend/orders/urls.py" in content
    assert "from users.views import onboarding_chat_auth_token" in content
    assert "api/chat/auth-token" in content


def test_run_onboarding_generation_writes_merge_simulation_artifact(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-merge",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-merge"
    merge_path = run_root / "reports" / "merge-simulation.json"
    payload = json.loads(merge_path.read_text(encoding="utf-8"))

    assert result["merge_simulation_path"].endswith("reports/merge-simulation.json")
    assert merge_path.exists()
    assert payload["applied_generated_files"]
    assert payload["passed"] is True


def test_run_onboarding_generation_stops_when_merge_simulation_patch_apply_fails(tmp_path: Path, monkeypatch):
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

    def write_invalid_proposed_patch(*, source_root, generated_run_root, proposal_path, output_path) -> Path:
        patch_path = Path(output_path)
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text("not a valid patch\n", encoding="utf-8")
        return patch_path

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.write_unified_diff_draft",
        write_invalid_proposed_patch,
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-merge-fail",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-merge-fail"
    merge_path = run_root / "reports" / "merge-simulation.json"
    payload = json.loads(merge_path.read_text(encoding="utf-8"))

    assert result["current_state"] == "human_review_required"
    assert result["runtime_workspace"] == str(runtime_root / "food" / "food-run-merge-fail" / "workspace")
    assert payload["passed"] is False
    assert payload["failed_patch_artifacts"]


def test_run_onboarding_generation_writes_backend_evaluation_artifact(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-backend-eval",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-backend-eval"
    report_path = run_root / "reports" / "backend-evaluation.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["backend_evaluation_path"].endswith("reports/backend-evaluation.json")
    assert report_path.exists()
    assert payload["passed"] is True
    assert payload["checked_files"]


def test_run_onboarding_generation_writes_frontend_evaluation_artifact(tmp_path: Path):
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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-frontend-eval",
        agent_version="test-v1",
        approval_decisions={
            "analysis": "approve",
            "apply": "approve",
            "export": "approve",
        },
    )

    run_root = generated_root / "food" / "food-run-frontend-eval"
    report_path = run_root / "reports" / "frontend-evaluation.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["frontend_evaluation_path"].endswith("reports/frontend-evaluation.json")
    assert report_path.exists()
    assert payload["framework"] == "react"
    assert payload["mount_candidates"]


def test_run_onboarding_generation_parallel_validation(tmp_path: Path, monkeypatch):
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

    backend_started = threading.Event()
    frontend_started = threading.Event()
    call_log: list[str] = []
    log_lock = threading.Lock()

    def fake_backend_evaluation(*, runtime_workspace, report_root):
        with log_lock:
            call_log.append("backend_started")
        backend_started.set()
        assert frontend_started.wait(timeout=1.0), "frontend evaluation did not start in parallel"
        output_path = Path(report_root) / "backend-evaluation.json"
        output_path.write_text(json.dumps({"passed": True, "checked_files": ["backend/users/views.py"]}), encoding="utf-8")
        with log_lock:
            call_log.append("backend_completed")
        return output_path

    def fake_frontend_evaluation(*, runtime_workspace, report_root):
        with log_lock:
            call_log.append("frontend_started")
        frontend_started.set()
        assert backend_started.wait(timeout=1.0), "backend evaluation did not start in parallel"
        output_path = Path(report_root) / "frontend-evaluation.json"
        output_path.write_text(json.dumps({"passed": True, "framework": "react", "mount_candidates": ["frontend/src/App.js"]}), encoding="utf-8")
        (Path(report_root) / "frontend-build-validation.json").write_text(
            json.dumps({"build_passed": True}),
            encoding="utf-8",
        )
        with log_lock:
            call_log.append("frontend_completed")
        return output_path

    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.evaluate_backend_workspace",
        fake_backend_evaluation,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.evaluate_frontend_workspace",
        fake_frontend_evaluation,
    )

    role_runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": "Detected onboarding structure",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "plan generation",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Planner": lambda context: {
                "claim": "Generate overlay",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "generate overlay",
                "blocking_issue": "none",
                "metadata": {},
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
            "Validator": lambda context: {
                "claim": "Validation passed",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low",
                "next_action": "request export approval",
                "blocking_issue": "none",
                "metadata": {},
            },
            "Diagnostician": lambda context: {
                "claim": "No diagnosis needed",
                "evidence": context["evidence"],
                "confidence": 0.7,
                "risk": "low",
                "next_action": "request_human_review",
                "blocking_issue": "none",
                "metadata": {"should_retry": False},
            },
        }
    )

    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)
    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-parallel-validation",
        agent_version="test-v1",
        role_runner=role_runner,
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
        event_store=event_store,
    )

    assert set(call_log) == {
        "backend_started",
        "frontend_started",
        "backend_completed",
        "frontend_completed",
    }
    entries = [json.loads(entry) for entry in fake.lrange(result["run_event_stream"], 0, -1)]
    started_roles = [entry["payload"]["role"] for entry in entries if entry["event"] == "job.started"]
    completed_roles = [entry["payload"]["role"] for entry in entries if entry["event"] == "job.completed"]
    assert "BackendEvaluator" in started_roles
    assert "FrontendEvaluator" in started_roles
    assert "BackendEvaluator" in completed_roles
    assert "FrontendEvaluator" in completed_roles
    assert Path(result["backend_evaluation_path"]).exists()
    assert Path(result["frontend_evaluation_path"]).exists()


def test_run_onboarding_generation_writes_fastapi_registration_diff_draft(tmp_path: Path):
    source_root = tmp_path / "shop"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "app").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="shop",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="shop-run-fastapi",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    content = (generated_root / "shop" / "shop-run-fastapi" / "patches" / "proposed.patch").read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert "+++ b/backend/app/main.py" in content
    assert "from backend.chat_auth import router as onboarding_chat_router" in content
    assert "app.include_router(onboarding_chat_router)" in content


def test_run_onboarding_generation_writes_flask_registration_diff_draft(tmp_path: Path):
    source_root = tmp_path / "shop"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="shop",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="shop-run-flask",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    content = (generated_root / "shop" / "shop-run-flask" / "patches" / "proposed.patch").read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert "+++ b/backend/app.py" in content
    assert "from backend.chat_auth import chat_auth_bp" in content
    assert "app.register_blueprint(chat_auth_bp)" in content


def test_run_onboarding_generation_writes_frontend_mount_diff_draft(tmp_path: Path):
    source_root = tmp_path / "shop"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n    return <main>Home</main>;\n}\n",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="shop",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="shop-run-frontend-diff",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve", "export": "approve"},
    )

    content = (generated_root / "shop" / "shop-run-frontend-diff" / "patches" / "proposed.patch").read_text(encoding="utf-8")

    assert result["current_state"] == "completed"
    assert "+++ b/frontend/src/App.js" in content
    assert 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";' in content
    assert "<SharedChatbotWidget />" in content


def test_run_onboarding_generation_handles_sources_without_trailing_newlines(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }",
        encoding="utf-8",
    )

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-no-newline",
        agent_version="test-v1",
        approval_decisions={"analysis": "approve", "apply": "approve"},
    )

    merge_path = generated_root / "food" / "food-run-no-newline" / "reports" / "merge-simulation.json"
    payload = json.loads(merge_path.read_text(encoding="utf-8"))

    assert result["current_state"] != "human_review_required"
    assert payload["passed"] is True
