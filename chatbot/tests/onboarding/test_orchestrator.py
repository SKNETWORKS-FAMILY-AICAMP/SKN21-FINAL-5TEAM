import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.orchestrator import run_onboarding_generation
from chatbot.src.onboarding.role_runner import RoleRunner


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

    result = run_onboarding_generation(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        runtime_root=runtime_root,
        run_id="food-run-001",
        agent_version="test-v1",
    )

    run_root = generated_root / "food" / "food-run-001"
    runtime_workspace = runtime_root / "food" / "food-run-001" / "workspace"

    assert result["run_root"] == str(run_root)
    assert result["runtime_workspace"] == str(runtime_workspace)

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis"]["product_api"] == ["/api/products/"]

    assert (run_root / "files" / "backend" / "chat_auth.py").exists()
    assert (run_root / "files" / "backend" / "order_adapter_client.py").exists()
    assert (run_root / "files" / "backend" / "product_adapter_client.py").exists()
    assert (run_root / "patches" / "frontend_widget_mount.patch").exists()
    assert (run_root / "smoke-tests" / "login.sh").exists()
    assert (run_root / "reports" / "smoke-results.json").exists()
    assert (run_root / "reports" / "smoke-summary.json").exists()
    assert runtime_workspace.exists()

    smoke_results = json.loads((run_root / "reports" / "smoke-results.json").read_text(encoding="utf-8"))
    assert len(smoke_results) >= 1
    assert smoke_results[0]["returncode"] == 0

    smoke_summary = json.loads((run_root / "reports" / "smoke-summary.json").read_text(encoding="utf-8"))
    assert smoke_summary["passed"] is True
    assert smoke_summary["required_failures"] == []


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
                "metadata": {"should_retry": True},
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
