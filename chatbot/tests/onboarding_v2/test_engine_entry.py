import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.engine import run_onboarding_generation_v2
from chatbot.src.onboarding_v2.models.repair import RepairDecision
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePlan, BackendRuntimePrepResult, BackendRuntimeState


def test_engine_entry_returns_v2_payload(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.run_runtime_smoke",
        lambda **kwargs: {
            "passed": True,
            "results": [],
            "failure_summary": "smoke passed",
            "related_files": [],
        },
    )
    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2",
    )

    assert result["engine"] == "v2"
    assert result["status"] == "exported"
    assert result["latest_analysis_artifact"].endswith("v0001.json")
    assert result["latest_repair_artifact"] is None
    assert result["repair_attempt_count"] == 0


def test_engine_entry_rewinds_validation_failures(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    smoke_attempts = {"count": 0}

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )

    def _run_smoke(**kwargs):
        smoke_attempts["count"] += 1
        if smoke_attempts["count"] == 1:
            return {
                "passed": False,
                "results": [{"step_id": "order-api", "returncode": 1, "stderr": "order failed"}],
                "failure_summary": "step order-api returned 500",
                "related_files": ["backend/orders/views.py"],
            }
        return {
            "passed": True,
            "results": [],
            "failure_summary": "smoke passed",
            "related_files": [],
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.run_runtime_smoke",
        _run_smoke,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="smoke_step_order_api_returned_500",
            diagnosis="rerun validation after smoke failure",
            rewind_to="validation",
            preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
            required_rechecks=["smoke"],
            additional_discovery=[],
            artifact_overrides={},
            stop=False,
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-repair",
        llm_provider="openai",
        llm_model="gpt-5-mini",
    )

    assert result["status"] == "exported"
    assert result["repair_attempt_count"] == 1
    assert result["latest_repair_artifact"].endswith("v0001.json")
    assert smoke_attempts["count"] == 2


def test_engine_entry_stops_after_repeated_failure_signature(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.run_runtime_smoke",
        lambda **kwargs: {
            "passed": False,
            "results": [{"step_id": "login", "returncode": 1, "stderr": "login failed"}],
            "failure_summary": "step login returned 500",
            "related_files": ["backend/users/views.py"],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="smoke_step_login_returned_500",
            diagnosis="rerun validation",
            rewind_to="validation",
            preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
            required_rechecks=["smoke"],
            additional_discovery=[],
            artifact_overrides={},
            stop=False,
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-repair-stop",
        llm_provider="openai",
        llm_model="gpt-5-mini",
    )

    assert result["status"] == "failed_human_review"
    assert result["repair_attempt_count"] == 4
