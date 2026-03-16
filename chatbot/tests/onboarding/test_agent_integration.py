import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.orchestrator import run_onboarding_generation
from chatbot.src.onboarding.role_runner import RoleRunner
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge


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
    assert any("backend framework: django" in item for item in analyzer_context["evidence"])
    assert any("auth style: unknown" in item for item in analyzer_context["evidence"])
    assert planner_context["analysis"]["product_api"] == ["/api/products/"]
    assert planner_context["recommended_outputs"] == [
        "chat_auth",
        "order_adapter",
        "product_adapter",
        "frontend_patch",
    ]
    assert any("recommended outputs: ['chat_auth', 'order_adapter', 'product_adapter', 'frontend_patch']" in item for item in planner_context["evidence"])
    assert any("route prefixes: []" in item for item in planner_context["evidence"])
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
    ]
    assert generator_context["proposed_patches"] == ["patches/frontend_widget_mount.patch"]


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
