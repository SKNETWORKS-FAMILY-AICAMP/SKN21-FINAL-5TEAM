import os
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePlan, BackendRuntimePrepResult, BackendRuntimeState
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding_v2.storage import ArtifactStore
from chatbot.src.onboarding_v2.validation.runner import (
    _evaluate_widget_order_flow_report,
    _enforce_required_rechecks,
    run_validation,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


def _build_food_runtime_artifacts(tmp_path: Path):
    generated_root = tmp_path / "generated" / "food" / "food-run-v2"
    runtime_root = tmp_path / "runtime"
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    snapshot = analysis_bundle.snapshot
    planning_bundle = build_planning_bundle(
        snapshot=snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    plan = planning_bundle.integration_plan
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "food",
    )
    apply_result = apply_edit_program(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        runtime_root=runtime_root,
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )
    artifact_store = ArtifactStore(generated_root)
    analysis_ref = artifact_store.write_json_artifact(stage="analysis", artifact_type="snapshot", payload=snapshot.model_dump(mode="json"), producer="test")
    plan_ref = artifact_store.write_json_artifact(stage="planning", artifact_type="integration-plan", payload=plan.model_dump(mode="json"), producer="test")
    compile_ref = artifact_store.write_json_artifact(stage="compile", artifact_type="host-edit-program", payload=program.host_program.model_dump(mode="json"), producer="test")
    apply_ref = artifact_store.write_json_artifact(stage="apply", artifact_type="apply-result", payload=apply_result.model_dump(mode="json"), producer="test")
    _, replay_result, replay_ref = export_and_replay(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        host_baseline_root=apply_result.host_source_snapshot_path,
        chatbot_baseline_root=apply_result.chatbot_source_snapshot_path,
        host_runtime_workspace=apply_result.host_workspace_path,
        chatbot_runtime_workspace=apply_result.chatbot_workspace_path,
        host_allowed_targets=apply_result.host_applied_files,
        chatbot_allowed_targets=apply_result.chatbot_applied_files,
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


def _build_food_plan():
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    return planning_bundle.integration_plan


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
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot adapter auth passed",
            "validated_user": {"id": "7", "siteId": "food"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget order e2e passed",
            "covered_flows": ["list_orders", "get_order_status", "cancel", "refund", "exchange"],
            "flow_reports": {},
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is True
    assert [check.name for check in bundle.checks] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
        "widget_bundle_fetch",
        "host_auth_bootstrap",
        "chatbot_adapter_auth",
        "widget_order_e2e",
        "replay_apply",
        "replay_validation",
    ]
    assert bundle.checks[6].details["covered_flows"] == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
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
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert bundle.checks[0].name == "backend_runtime_prep"
    assert bundle.checks[0].passed is False
    assert bundle.failure_signature.startswith("backend_runtime_prep")


def test_validation_runner_requires_requested_rechecks():
    with pytest.raises(ValueError, match="required validation rechecks missing: host_auth_bootstrap"):
        _enforce_required_rechecks(
            required_rechecks=["host_auth_bootstrap"],
            checks=[
                {"name": "backend_runtime_prep", "passed": True},
                {"name": "widget_order_e2e", "passed": True},
            ],
        )


def test_validation_runner_fails_when_chatbot_runtime_boot_fails(monkeypatch, tmp_path: Path):
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
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "chatbot runtime boot failed: No module named 'ecommerce.backend'",
            "related_files": ["server_fastapi.py", "src/tools/order_tools.py"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert [check.name for check in bundle.checks][:3] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
    ]
    assert bundle.checks[2].passed is False
    assert bundle.failure_signature == "chatbot_runtime_boot_chatbot_runtime_boot_failed_no_module_named_ecommerce_backend"


def test_validation_runner_fails_when_widget_bundle_fetch_uses_host_origin(monkeypatch, tmp_path: Path):
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
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "widget bundle fetch failed: resolved to host origin",
            "target_url": "http://127.0.0.1:8000/widget.js",
            "related_files": ["frontend/src/App.js"],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert [check.name for check in bundle.checks][:4] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
        "widget_bundle_fetch",
    ]
    assert bundle.checks[3].passed is False
    assert bundle.failure_signature == "widget_bundle_fetch_widget_bundle_fetch_failed_resolved_to_host_origin"


def test_failure_signature_distinguishes_runtime_validation_phases():
    assert build_failure_signature(check_name="backend_runtime_prep", summary="dependency install failed") == "backend_runtime_prep_dependency_install_failed"
    assert build_failure_signature(check_name="backend_runtime_boot", summary="django app boot failed") == "backend_runtime_boot_django_app_boot_failed"
    assert build_failure_signature(check_name="chatbot_runtime_boot", summary="chatbot runtime boot failed: No module named 'ecommerce.backend'") == "chatbot_runtime_boot_chatbot_runtime_boot_failed_no_module_named_ecommerce_backend"
    assert build_failure_signature(check_name="widget_order_e2e", summary="show_order_list missing") == "widget_order_e2e_show_order_list_missing"


def test_widget_order_e2e_report_tracks_all_required_flows():
    result = _evaluate_widget_order_flow_report(
        plan=_build_food_plan(),
        flow_reports={
            "get_order_status": {"passed": True, "steps": []},
            "list_orders": {"steps": ["show_order_list"], "fragments": ["list-stream"]},
            "cancel": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["cancel-1", "cancel-2"]},
            "refund": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["refund-1", "refund-2"]},
            "exchange": {"steps": ["show_order_list", "show_option_list", "confirm_order_action"], "fragments": ["exchange-1", "exchange-2", "exchange-3"]},
        },
    )

    assert result.passed is True
    assert result.covered_flows == ["list_orders", "get_order_status", "cancel", "refund", "exchange"]


def test_widget_order_e2e_report_marks_missing_exchange_option_step_as_failure():
    result = _evaluate_widget_order_flow_report(
        plan=_build_food_plan(),
        flow_reports={
            "get_order_status": {"passed": True, "steps": []},
            "list_orders": {"steps": ["show_order_list"], "fragments": ["list-stream"]},
            "cancel": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["cancel-1", "cancel-2"]},
            "refund": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["refund-1", "refund-2"]},
            "exchange": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["exchange-1", "exchange-2"]},
        },
    )

    assert result.passed is False
    assert result.failure_summary == "show_option_list missing"


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
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    captured = {}

    def _bootstrap(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        _bootstrap,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot adapter auth passed",
            "validated_user": {"id": "7", "siteId": "food"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget order e2e passed",
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)
    manifest_path = runtime_context["generated_root"] / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
        onboarding_credentials={"email": "test1@example.com", "password": "password123"},
    )

    assert bundle.passed is True
    assert captured["kwargs"]["onboarding_credentials"]["email"] == "test1@example.com"
    assert not manifest_path.exists()


def test_validation_runner_requires_site_id_in_host_bootstrap(monkeypatch, tmp_path: Path):
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
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "host auth bootstrap missing site_id",
            "related_files": ["backend/chat_auth.py"],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {"passed": True, "failure_summary": "chatbot adapter auth passed", "related_files": []},
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {"passed": True, "failure_summary": "widget order e2e passed", "related_files": []},
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert bundle.checks[4].name == "host_auth_bootstrap"
    assert bundle.failure_signature == "host_auth_bootstrap_host_auth_bootstrap_missing_site_id"
