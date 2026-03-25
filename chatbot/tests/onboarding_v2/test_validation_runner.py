import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePlan, BackendRuntimePrepResult, BackendRuntimeState
from chatbot.src.onboarding_v2.planning import build_integration_plan
from chatbot.src.onboarding_v2.storage import ArtifactStore
from chatbot.src.onboarding_v2.validation.runner import run_validation
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


def _build_food_runtime_artifacts(tmp_path: Path):
    generated_root = tmp_path / "generated" / "food" / "food-run-v2"
    runtime_root = tmp_path / "runtime"
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(snapshot)
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")
    apply_result = apply_edit_program(
        source_root=ROOT / "food",
        runtime_root=runtime_root,
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )
    artifact_store = ArtifactStore(generated_root)
    analysis_ref = artifact_store.write_json_artifact(stage="analysis", artifact_type="snapshot", payload=snapshot.model_dump(mode="json"), producer="test")
    plan_ref = artifact_store.write_json_artifact(stage="planning", artifact_type="integration-plan", payload=plan.model_dump(mode="json"), producer="test")
    compile_ref = artifact_store.write_json_artifact(stage="compile", artifact_type="edit-program", payload=program.model_dump(mode="json"), producer="test")
    apply_ref = artifact_store.write_json_artifact(stage="apply", artifact_type="apply-result", payload=apply_result.model_dump(mode="json"), producer="test")
    _, replay_result, replay_ref = export_and_replay(
        source_root=ROOT / "food",
        runtime_workspace=apply_result.workspace_path,
        runtime_root=runtime_root,
        run_root=generated_root,
        site="food",
        run_id="food-run-v2",
        artifact_store=artifact_store,
    )
    return {
        "generated_root": generated_root,
        "snapshot": snapshot,
        "plan": plan,
        "apply_result": apply_result,
        "replay_result": replay_result,
        "artifact_refs": {
            "analysis": analysis_ref,
            "planning": plan_ref,
            "compile": compile_ref,
            "apply": apply_ref,
            "replay": replay_ref,
        },
    }


def test_validation_runner_normalizes_checks(monkeypatch, tmp_path: Path):
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
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        runtime_workspace=runtime_context["apply_result"].workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is True
    assert [check.name for check in bundle.checks] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "frontend_evaluation",
        "smoke",
        "replay_apply",
        "replay_validation",
    ]


def test_validation_runner_does_not_allow_static_fallback_success(monkeypatch, tmp_path: Path):
    runtime_context = _build_food_runtime_artifacts(tmp_path)
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(
            framework="django",
            passed=False,
            failure_summary="dependency install failed: missing corsheaders",
        ),
    )

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        runtime_workspace=runtime_context["apply_result"].workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert bundle.checks[0].name == "backend_runtime_prep"
    assert bundle.checks[0].passed is False
    assert bundle.failure_signature.startswith("backend_runtime_prep")


def test_failure_signature_distinguishes_runtime_validation_phases():
    assert build_failure_signature(check_name="backend_runtime_prep", summary="dependency install failed") == "backend_runtime_prep_dependency_install_failed"
    assert build_failure_signature(check_name="backend_runtime_boot", summary="django app boot failed") == "backend_runtime_boot_django_app_boot_failed"
    assert build_failure_signature(check_name="smoke", summary="step order-api returned 500") == "smoke_step_order_api_returned_500"


def test_validation_runner_uses_explicit_credentials_without_manifest(monkeypatch, tmp_path: Path):
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
    captured = {}

    def _smoke(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "passed": True,
            "results": [],
            "failure_summary": "smoke passed",
            "related_files": [],
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.run_runtime_smoke",
        _smoke,
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)
    manifest_path = runtime_context["generated_root"] / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        runtime_workspace=runtime_context["apply_result"].workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
        onboarding_credentials={"email": "test1@example.com", "password": "password123"},
    )

    assert bundle.passed is True
    assert captured["kwargs"]["onboarding_credentials"]["email"] == "test1@example.com"
    assert not manifest_path.exists()
