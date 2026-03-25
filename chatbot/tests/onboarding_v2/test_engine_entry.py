import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.engine import run_onboarding_generation_v2
from chatbot.src.onboarding_v2.compile.preflight import CompilePreflightResult
from chatbot.src.onboarding_v2.models.repair import RepairDecision
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
)


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


def test_engine_entry_returns_v2_payload(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
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
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )
    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["engine"] == "v2"
    assert result["status"] == "exported"
    assert result["latest_analysis_artifact"].endswith("v0001.json")
    assert result["latest_compile_artifact"].endswith("host-edit-program/v0001.json")
    assert result["latest_chatbot_compile_artifact"].endswith("chatbot-edit-program/v0001.json")
    assert result["latest_compile_preflight_artifact"].endswith("compile-preflight/v0001.json")
    assert result["compile_preflight_result"] == {
        "passed": True,
        "failure_code": None,
        "failure_summary": None,
        "related_files": [],
        "details": {"import_smoke": "passed"},
    }
    assert result["approved_patch_path"].endswith("host-approved.patch/v0001.patch")
    assert result["chatbot_approved_patch_path"].endswith("chatbot-approved.patch/v0001.patch")
    assert result["latest_repair_artifact"] is None
    assert result["repair_attempt_count"] == 0


def test_engine_entry_passes_snapshot_roots_and_allowlists_to_export(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
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
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )

    from chatbot.src.onboarding_v2.export.replay import export_and_replay as real_export_and_replay

    captured: dict[str, object] = {}

    def _capturing_export_and_replay(**kwargs):
        captured.update(kwargs)
        return real_export_and_replay(**kwargs)

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.export_and_replay",
        _capturing_export_and_replay,
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-export-args",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert str(captured["host_baseline_root"]).endswith("source-snapshot/host")
    assert str(captured["chatbot_baseline_root"]).endswith("source-snapshot/chatbot")
    assert "frontend/src/App.js" in set(captured["host_allowed_targets"])
    assert captured["chatbot_allowed_targets"]


def test_engine_stops_at_compile_when_chatbot_preflight_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=False,
            failure_code="banned_import_detected",
            failure_summary="banned import detected: ecommerce.backend",
            related_files=["src/tools/order_tools.py"],
            details={"matches": [{"pattern": "ecommerce.backend"}]},
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.export_and_replay",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("export should not run")),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="banned_import_detected",
            diagnosis="stop on compile preflight failure",
            rewind_to="compile",
            preserve_artifacts=["analysis", "planning", "compile", "apply"],
            required_rechecks=["compile_preflight"],
            additional_discovery=[],
            artifact_overrides={},
            stop=True,
            stop_reason="compile_preflight_failed",
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-preflight-fail",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "failed_human_review"
    assert result["latest_export_artifact"] is None
    assert result["latest_validation_artifact"] is None
    assert result["latest_compile_preflight_artifact"].endswith("compile-preflight/v0001.json")
    assert result["compile_preflight_result"] == {
        "passed": False,
        "failure_code": "banned_import_detected",
        "failure_summary": "banned import detected: ecommerce.backend",
        "related_files": ["src/tools/order_tools.py"],
        "details": {"matches": [{"pattern": "ecommerce.backend"}]},
    }
    assert result["failure_signature"].startswith("chatbot_runtime_import")
    assert result["repair_attempt_count"] == 1


def test_engine_reports_compile_stage_on_preflight_crash(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: (_ for _ in ()).throw(RuntimeError("preflight boom")),
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="chatbot_runtime_import_preflight_boom",
            diagnosis="stop on compile preflight crash",
            rewind_to="compile",
            preserve_artifacts=["analysis", "planning", "compile", "apply"],
            required_rechecks=["compile_preflight"],
            additional_discovery=[],
            artifact_overrides={},
            stop=True,
            stop_reason="compile_preflight_crashed",
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-preflight-crash",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "failed_human_review"
    assert result["latest_export_artifact"] is None
    assert result["latest_validation_artifact"] is None
    assert result["latest_compile_preflight_artifact"] is None
    assert result["failure_signature"].startswith("chatbot_runtime_import")
    assert result["repair_attempt_count"] == 1


def test_engine_entry_rewinds_validation_failures(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
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
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )

    def _host_bootstrap(**kwargs):
        smoke_attempts["count"] += 1
        if smoke_attempts["count"] == 1:
            return {
                "passed": False,
                "failure_summary": "host auth bootstrap missing site_id",
                "bootstrap_payload": {
                    "authenticated": True,
                    "site_id": "",
                    "access_token": "session-token",
                    "user": {"id": "7"},
                },
                "related_files": ["backend/chat_auth.py"],
            }
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
        _host_bootstrap,
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
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )
    from chatbot.src.onboarding_v2 import engine as onboarding_engine

    compile_preflight_calls = {"count": 0}
    original_run_compile_preflight_stage = onboarding_engine.run_compile_preflight_stage

    def _counting_compile_preflight_stage(*args, **kwargs):
        compile_preflight_calls["count"] += 1
        return original_run_compile_preflight_stage(*args, **kwargs)

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_compile_preflight_stage",
        _counting_compile_preflight_stage,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="host_auth_bootstrap_missing_site_id",
            diagnosis="rerun validation after host auth bootstrap failure",
            rewind_to="validation",
            preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
            required_rechecks=["host_auth_bootstrap"],
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
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert result["repair_attempt_count"] == 1
    assert result["latest_repair_artifact"].endswith("v0001.json")
    assert smoke_attempts["count"] == 2
    assert compile_preflight_calls["count"] == 1


def test_engine_entry_derives_effective_compile_rewind_from_overrides(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
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
    host_bootstrap_attempts = {"count": 0}

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

    def _host_bootstrap(**kwargs):
        host_bootstrap_attempts["count"] += 1
        if host_bootstrap_attempts["count"] == 1:
            return {
                "passed": False,
                "failure_summary": "host auth bootstrap missing site_id",
                "bootstrap_payload": {
                    "authenticated": True,
                    "site_id": "",
                    "access_token": "session-token",
                    "user": {"id": "7"},
                },
                "related_files": ["backend/chat_auth.py"],
            }
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
        _host_bootstrap,
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
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )
    from chatbot.src.onboarding_v2 import engine as onboarding_engine

    compile_calls = {"count": 0}
    apply_calls = {"count": 0}
    original_run_compile_stage = onboarding_engine.run_compile_stage
    original_run_apply_stage = onboarding_engine.run_apply_stage

    def _counting_compile_stage(*args, **kwargs):
        compile_calls["count"] += 1
        return original_run_compile_stage(*args, **kwargs)

    def _counting_apply_stage(*args, **kwargs):
        apply_calls["count"] += 1
        return original_run_apply_stage(*args, **kwargs)

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_compile_stage",
        _counting_compile_stage,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_apply_stage",
        _counting_apply_stage,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="host_auth_bootstrap_missing_site_id",
            diagnosis="compile override required for auth bootstrap repair",
            rewind_to="validation",
            preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
            required_rechecks=["compile_preflight"],
            additional_discovery=[],
            artifact_overrides={"compile": {"supporting_files": [{"path": "backend/chat_auth.py"}]}},
            stop=False,
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-effective-rewind",
        llm_provider="openai",
        llm_model="gpt-5-mini",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert result["repair_attempt_count"] == 1
    assert host_bootstrap_attempts["count"] == 2
    assert compile_calls["count"] == 2
    assert apply_calls["count"] == 2

    repair_artifact = json.loads(Path(result["latest_repair_artifact"]).read_text(encoding="utf-8"))
    assert repair_artifact["payload"]["requested_rewind_to"] == "validation"
    assert repair_artifact["payload"]["effective_rewind_to"] == "compile"

    run_summary = json.loads(
        (Path(result["run_root"]) / "views" / "run-summary.json").read_text(encoding="utf-8")
    )
    assert run_summary["latest_rewind_to"] == "compile"

    events = [
        json.loads(line)
        for line in (Path(result["run_root"]) / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decision_event = next(event for event in events if event["event_type"] == "repair_decision_emitted")
    rerun_event = next(event for event in events if event["event_type"] == "stage_rerun_started")
    assert decision_event["requested_rewind_to"] == "validation"
    assert decision_event["effective_rewind_to"] == "compile"
    assert rerun_event["stage"] == "compile"
    assert rerun_event["rewind_to"] == "compile"
    assert rerun_event["requested_rewind_to"] == "validation"
    assert rerun_event["effective_rewind_to"] == "compile"

    debug_payload = json.loads(
        (Path(result["run_root"]) / "debug" / "llm" / "repair" / "attempt-0001-effective-rewind.json").read_text(
            encoding="utf-8"
        )
    )
    assert debug_payload["normalized_response"]["requested_rewind_to"] == "validation"
    assert debug_payload["normalized_response"]["effective_rewind_to"] == "compile"


def test_engine_entry_stops_after_repeated_failure_signature(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
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
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": ["backend/chat_auth.py"],
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
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="host_auth_bootstrap_missing_site_id",
            diagnosis="rerun validation",
            rewind_to="validation",
            preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
            required_rechecks=["host_auth_bootstrap"],
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
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "failed_human_review"
    assert result["repair_attempt_count"] == 4


def test_engine_rewind_preserves_only_requested_stages():
    from chatbot.src.onboarding_v2 import engine as onboarding_engine
    from chatbot.src.onboarding_v2.models import ArtifactRef

    state = onboarding_engine._RunState(
        analysis_ref=ArtifactRef(stage="analysis", artifact_type="snapshot", version=1, path="a.json", content_hash="a"),
        plan_ref=ArtifactRef(stage="planning", artifact_type="integration-plan", version=1, path="p.json", content_hash="p"),
        compile_ref=ArtifactRef(stage="compile", artifact_type="host-edit-program", version=1, path="c.json", content_hash="c"),
        chatbot_compile_ref=ArtifactRef(stage="compile", artifact_type="chatbot-edit-program", version=1, path="cc.json", content_hash="cc"),
        apply_ref=ArtifactRef(stage="apply", artifact_type="apply-result", version=1, path="apply.json", content_hash="apply"),
        export_bundle_ref=ArtifactRef(stage="export", artifact_type="export-bundle", version=1, path="e.json", content_hash="e"),
        validation_ref=ArtifactRef(stage="validation", artifact_type="validation-bundle", version=1, path="v.json", content_hash="v"),
    )

    onboarding_engine._clear_state_for_failure(
        state=state,
        failed_stage="validation",
        rewind_to="planning",
        preserve_artifacts=["analysis"],
    )

    assert state.analysis_ref is not None
    assert state.plan_ref is None
    assert state.compile_ref is None
    assert state.chatbot_compile_ref is None
    assert state.apply_ref is None
    assert state.export_bundle_ref is None
    assert state.validation_ref is None
