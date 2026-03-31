import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.engine import (
    _RunState,
    _apply_planning_overrides,
    _build_retrieval_smoke_payload,
    _clear_state_for_failure,
    _reconcile_preserved_indexing_after_planning,
    run_onboarding_generation_v2,
)
from chatbot.src.onboarding_v2.compile.preflight import CompilePreflightResult
from chatbot.src.onboarding_v2.models import ArtifactRef
from chatbot.src.onboarding_v2.models.repair import RepairDecision
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    ReplayResult,
)
from chatbot.src.onboarding_v2.analysis import analyzer as analyzer_module
from chatbot.src.onboarding_v2.models.planning import RagCorpusPlan, RetrievalIndexPlan
from chatbot.src.onboarding_v2.planning import planner as planner_module


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


@pytest.fixture(autouse=True)
def _stub_indexing_execution(monkeypatch):
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.execute_indexing_plan",
        lambda *, plan, **kwargs: {
            "site_id": plan.site_id,
            "site_slug": plan.site_slug,
            "corpora": {
                item.corpus: {
                    "status": "failed",
                    "enabled": False,
                    "documents_indexed": 0,
                    "collection_alias": item.collection_alias,
                    "build_collection": item.build_collection,
                    "loader_strategy": item.loader_strategy,
                    "warning_codes": ["stubbed_for_engine_test"],
                    "alias_swapped": False,
                    "smoke_passed": False,
                }
                for item in plan.corpora
            },
        },
    )


def _artifact_ref(stage: str, artifact_type: str, path: str) -> ArtifactRef:
    return ArtifactRef(
        stage=stage,
        artifact_type=artifact_type,
        version=1,
        path=path,
        content_hash="test-hash",
    )


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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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


def test_engine_entry_writes_llm_usage_summary_artifact(monkeypatch, tmp_path: Path):
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

    def _fake_invoke_structured_stage(
        *,
        stage,
        phase,
        response_model,
        fallback_payload,
        usage_store=None,
        provider,
        model,
        attempt,
        **kwargs,
    ):
        del kwargs
        if usage_store is not None:
            usage_store.append(
                stage=stage,
                phase=phase,
                attempt=attempt,
                provider=provider,
                model=model,
                usage={
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "cached_input_tokens": 200,
                    "total_tokens": 1500,
                },
                extra={"status": "parsed"},
            )
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(analyzer_module, "invoke_structured_stage", _fake_invoke_structured_stage)
    monkeypatch.setattr(planner_module, "invoke_structured_stage", _fake_invoke_structured_stage)
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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        run_id="food-run-v2-llm-usage",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert result["latest_llm_usage_artifact"].endswith("llm-usage-summary/v0001.json")

    usage_artifact = json.loads(Path(result["latest_llm_usage_artifact"]).read_text(encoding="utf-8"))
    assert usage_artifact["payload"]["totals"]["estimated_total_cost_usd"] > 0
    assert usage_artifact["payload"]["calls"]


def test_engine_entry_scopes_tool_runtime_to_analysis_only(monkeypatch, tmp_path: Path):
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
    observed: list[tuple[str, str, object]] = []

    def _fake_invoke_structured_stage(
        *,
        stage,
        phase,
        response_model,
        fallback_payload,
        tool_runtime=None,
        **kwargs,
    ):
        del kwargs
        observed.append((stage, phase, tool_runtime))
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(analyzer_module, "invoke_structured_stage", _fake_invoke_structured_stage)
    monkeypatch.setattr(planner_module, "invoke_structured_stage", _fake_invoke_structured_stage)
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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        run_id="food-run-v2-tool-scope",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    analysis_tool_runtimes = [tool_runtime for stage, _phase, tool_runtime in observed if stage == "analysis"]
    planning_tool_runtimes = [tool_runtime for stage, _phase, tool_runtime in observed if stage == "planning"]
    assert analysis_tool_runtimes
    assert all(tool_runtime is not None for tool_runtime in analysis_tool_runtimes)
    assert planning_tool_runtimes
    assert all(tool_runtime is None for tool_runtime in planning_tool_runtimes)


def test_engine_entry_records_indexing_stage_start_before_export_completion(monkeypatch, tmp_path: Path):
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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        run_id="food-run-v2-indexing-order",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    events = [
        json.loads(line)
        for line in (Path(result["run_root"]) / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    export_completed_index = next(
        index
        for index, event in enumerate(events)
        if event["stage"] == "export" and event["event_type"] == "stage_completed"
    )
    indexing_started_index = next(
        index
        for index, event in enumerate(events)
        if event["stage"] == "indexing" and event["event_type"] == "stage_started"
    )

    assert indexing_started_index < export_completed_index


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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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


def test_apply_planning_overrides_updates_nested_chatbot_response_contract():
    analysis_bundle = analyzer_module.build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    plan = planner_module.build_integration_plan(
        analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )

    updated = _apply_planning_overrides(
        plan=plan,
        overrides={
            "chatbot_bridge": {
                "response_contract": {
                    "user_profile": "wrapped_user",
                }
            }
        },
    )

    assert updated.chatbot_bridge.response_contract.user_profile == "wrapped_user"
    assert updated.chatbot_bridge.response_contract.order_profile == (
        plan.chatbot_bridge.response_contract.order_profile
    )
    assert updated.chatbot_bridge.response_contract.order_status_profile == (
        plan.chatbot_bridge.response_contract.order_status_profile
    )


def test_clear_state_for_failure_preserves_indexing_across_planning_rewind():
    state = _RunState(
        indexing_result={"site_id": "food", "site_slug": "food", "corpora": {"faq": {"status": "completed"}}},
        retrieval_source_manifest_ref=_artifact_ref("indexing", "retrieval-source-manifest", "v0001.json"),
        indexing_plan_ref=_artifact_ref("indexing", "indexing-plan", "v0001.json"),
        indexing_result_ref=_artifact_ref("indexing", "indexing-result", "v0001.json"),
        retrieval_smoke_ref=_artifact_ref("indexing", "retrieval-smoke", "v0001.json"),
        validation_ref=_artifact_ref("validation", "validation-bundle", "v0001.json"),
    )

    _clear_state_for_failure(
        state=state,
        failed_stage="validation",
        rewind_to="planning",
        preserve_artifacts=["analysis"],
    )

    assert state.indexing_result is not None
    assert state.indexing_result_ref is not None
    assert state.validation_ref is None


def test_reconcile_preserved_indexing_after_planning_reapplies_when_retrieval_plan_matches():
    analysis_bundle = analyzer_module.build_analysis_bundle(site="food", source_root=ROOT / "food")
    original_plan = planner_module.build_integration_plan(
        analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    state = _RunState(
        plan=original_plan.model_copy(),
        indexing_result={
            "site_id": "food",
            "site_slug": "food",
            "corpora": {
                "faq": {
                    "status": "completed",
                    "enabled": True,
                    "documents_indexed": 42,
                }
            },
        },
        retrieval_source_manifest_ref=_artifact_ref("indexing", "retrieval-source-manifest", "v0001.json"),
        indexing_plan_ref=_artifact_ref("indexing", "indexing-plan", "v0001.json"),
        indexing_result_ref=_artifact_ref("indexing", "indexing-result", "v0001.json"),
        retrieval_smoke_ref=_artifact_ref("indexing", "retrieval-smoke", "v0001.json"),
    )

    _reconcile_preserved_indexing_after_planning(
        state=state,
        previous_retrieval_plan=original_plan.retrieval_index_plan,
    )

    assert state.indexing_result is not None
    assert state.plan is not None
    assert state.plan.host_backend.enabled_retrieval_corpora == ["faq"]
    assert state.plan.host_backend.capability_profile == "order_cs_plus_retrieval"


def test_reconcile_preserved_indexing_after_planning_clears_when_retrieval_plan_changes():
    analysis_bundle = analyzer_module.build_analysis_bundle(site="food", source_root=ROOT / "food")
    original_plan = planner_module.build_integration_plan(
        analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    changed_plan = original_plan.model_copy(
        update={
            "retrieval_index_plan": RetrievalIndexPlan(
                site_id="food",
                site_slug="food",
                corpora=[
                    *list(original_plan.retrieval_index_plan.corpora),
                    RagCorpusPlan(
                        corpus="policy",
                        chunking_strategy="markdown_sections",
                        collection_alias="food-policy",
                        loader_strategy="static_files",
                        build_collection="food_policy_v2",
                        minimum_expected_documents=1,
                    ),
                ],
            )
        }
    )
    state = _RunState(
        plan=changed_plan,
        indexing_result={
            "site_id": "food",
            "site_slug": "food",
            "corpora": {
                "faq": {
                    "status": "completed",
                    "enabled": True,
                    "documents_indexed": 42,
                }
            },
        },
        retrieval_source_manifest_ref=_artifact_ref("indexing", "retrieval-source-manifest", "v0001.json"),
        indexing_plan_ref=_artifact_ref("indexing", "indexing-plan", "v0001.json"),
        indexing_result_ref=_artifact_ref("indexing", "indexing-result", "v0001.json"),
        retrieval_smoke_ref=_artifact_ref("indexing", "retrieval-smoke", "v0001.json"),
    )

    _reconcile_preserved_indexing_after_planning(
        state=state,
        previous_retrieval_plan=original_plan.retrieval_index_plan,
    )

    assert state.indexing_result is None
    assert state.indexing_result_ref is None
    assert state.retrieval_smoke_ref is None


def test_engine_entry_stops_at_export_when_replay_verification_fails(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "host" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
        listen_port=8000,
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
        listen_port=runtime_plan.listen_port,
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
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace, scan_paths=None: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )

    def _fake_export_and_replay(**kwargs):
        artifact_store = kwargs["artifact_store"]
        host_patch_ref = artifact_store.write_text_artifact(
            stage="export",
            artifact_type="host-approved.patch",
            content="",
            suffix=".patch",
        )
        chatbot_patch_ref = artifact_store.write_text_artifact(
            stage="export",
            artifact_type="chatbot-approved.patch",
            content="",
            suffix=".patch",
        )
        replay_result = ReplayResult(
            replay_workspace_path=str(tmp_path / "replay"),
            host_replay_workspace_path=str(tmp_path / "replay" / "host"),
            chatbot_replay_workspace_path=str(tmp_path / "replay" / "chatbot"),
            host_patch_path="host.patch",
            chatbot_patch_path="chatbot.patch",
            passed=False,
            target_match_passed=False,
            static_validation_passed=True,
            mismatched_targets=["host:backend/app.py"],
            static_validation_summary="replay static validation passed",
        )
        replay_ref = artifact_store.write_json_artifact(
            stage="export",
            artifact_type="replay-result",
            payload=replay_result.model_dump(mode="json"),
            producer="test",
            input_artifact_refs=[host_patch_ref, chatbot_patch_ref],
        )
        export_bundle_ref = artifact_store.write_json_artifact(
            stage="export",
            artifact_type="export-bundle",
            payload={
                "host_patch_artifact": host_patch_ref.model_dump(mode="json"),
                "chatbot_patch_artifact": chatbot_patch_ref.model_dump(mode="json"),
                "replay_artifact": replay_ref.model_dump(mode="json"),
                "replay_passed": False,
            },
            producer="test",
            input_artifact_refs=[host_patch_ref, chatbot_patch_ref, replay_ref],
        )
        return export_bundle_ref, replay_result, replay_ref

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.export_and_replay",
        _fake_export_and_replay,
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-export-fail",
        chatbot_server_base_url="http://localhost:8100",
        max_repair_attempts=1,
    )

    assert result["status"] == "failed_human_review"
    assert result["failure_signature"].startswith("export_")
    assert result["latest_validation_artifact"] is None


def test_engine_entry_passes_preflight_scan_paths(monkeypatch, tmp_path: Path):
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
        lambda plan, **kwargs: runtime_state,
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

    captured: dict[str, object] = {}

    def _capturing_preflight(workspace, scan_paths=None):
        captured["workspace"] = workspace
        captured["scan_paths"] = list(scan_paths or [])
        return CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        _capturing_preflight,
        raising=False,
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-preflight-scope",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert str(captured["workspace"]).endswith("/workspace/chatbot")
    assert set(captured["scan_paths"]) == {
        "src/adapters/setup.py",
        "src/adapters/generated/food/__init__.py",
        "src/adapters/generated/food/contracts.py",
        "src/adapters/generated/food/client.py",
        "src/adapters/generated/food/auth.py",
        "src/adapters/generated/food/mappers.py",
        "src/adapters/generated/food/adapter.py",
    }


def test_engine_stops_at_compile_when_chatbot_preflight_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        lambda workspace, scan_paths=None: (_ for _ in ()).throw(RuntimeError("preflight boom")),
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


def test_engine_stops_at_compile_when_host_import_smoke_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_chatbot_compile_preflight",
        lambda workspace, scan_paths=None: CompilePreflightResult(
            passed=True,
            failure_code=None,
            failure_summary=None,
            related_files=[],
            details={"import_smoke": "passed"},
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_flask_host_import_smoke",
        lambda host_workspace, entrypoint: CompilePreflightResult(
            passed=False,
            failure_code="host_backend_import_failed",
            failure_summary="host backend import failed",
            related_files=["app.py", "routes/order.py", "chat_auth.py"],
            details={"framework": "flask", "entrypoint": entrypoint},
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
            failure_signature="host_backend_import_host_backend_import_failed",
            diagnosis="stop on host import smoke failure",
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
        site="bilyeo",
        source_root=str(ROOT / "bilyeo"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="bilyeo-run-v2-host-smoke-fail",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "failed_human_review"
    assert result["latest_export_artifact"] is None
    assert result["latest_validation_artifact"] is None
    assert result["latest_host_import_smoke_artifact"].endswith("host-import-smoke/v0001.json")
    assert result["latest_indexing_artifact"] is None
    assert result["host_import_smoke_result"] == {
        "passed": False,
        "failure_code": "host_backend_import_failed",
        "failure_summary": "host backend import failed",
        "related_files": ["app.py", "routes/order.py", "chat_auth.py"],
        "details": {"framework": "flask", "entrypoint": "app.py"},
    }
    assert result["failure_signature"].startswith("host_backend_import")
    assert result["repair_attempt_count"] == 1
    summary = json.loads((Path(result["run_root"]) / "views" / "run-summary.json").read_text(encoding="utf-8"))
    assert summary["retrieval_status"] == {}
    assert summary["final_capability_profile"] == "order_cs_only"
    assert summary["enabled_retrieval_corpora"] == []


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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
            required_rechecks=["compile_preflight", "validation"],
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
    assert repair_artifact["payload"]["requested_required_rechecks"] == ["compile_preflight", "validation"]
    assert repair_artifact["payload"]["required_stage_rechecks"] == ["validation"]
    assert repair_artifact["payload"]["required_check_rechecks"] == ["compile_preflight"]

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
    assert debug_payload["normalized_response"]["required_stage_rechecks"] == ["validation"]
    assert debug_payload["normalized_response"]["required_check_rechecks"] == ["compile_preflight"]


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
        lambda plan, **kwargs: runtime_state,
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
        lambda workspace, scan_paths=None: CompilePreflightResult(
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
        max_repair_attempts=2,
    )

    assert result["status"] == "failed_human_review"
    assert result["repair_attempt_count"] == 2


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


def test_engine_entry_passes_analysis_overrides_into_analysis_rerun(monkeypatch, tmp_path: Path):
    from chatbot.src.onboarding_v2 import engine as onboarding_engine

    captured_analysis_overrides: list[dict[str, object]] = []
    original_build_analysis_bundle = onboarding_engine.build_analysis_bundle
    planning_calls = {"count": 0}

    def _capturing_build_analysis_bundle(**kwargs):
        captured_analysis_overrides.append(dict(kwargs.get("overrides") or {}))
        forwarded = dict(kwargs)
        forwarded.pop("overrides", None)
        forwarded.setdefault("ambiguity_retry_limit", 0)
        return original_build_analysis_bundle(**forwarded)

    def _planning_stage(**kwargs):
        planning_calls["count"] += 1
        if planning_calls["count"] == 1:
            raise onboarding_engine._StageFailure(
                stage="planning",
                failure_signature="planning_analysis_coverage_incomplete_for_planning_order_lookup_order_action",
                failure_summary="analysis coverage incomplete for planning: order_lookup, order_action",
                trigger_event_id="evt-planning",
                related_artifacts=[],
                related_files=[],
                input_artifact_versions={},
            )
        return None

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.build_analysis_bundle",
        _capturing_build_analysis_bundle,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_planning_stage",
        _planning_stage,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_compile_stage",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_apply_stage",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_export_stage",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.run_validation_stage",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.engine.diagnose_failure",
        lambda **kwargs: RepairDecision(
            failure_signature="planning_analysis_coverage_incomplete_for_planning_order_lookup_order_action",
            diagnosis="rerun analysis with forced order endpoint verification",
            rewind_to="planning",
            preserve_artifacts=["analysis"],
            required_rechecks=["analysis_contract_extraction", "planning_gate_coverage"],
            additional_discovery=[],
            artifact_overrides={
                "analysis": {
                    "force_verify_endpoints": [
                        {
                            "path": "/api/orders/",
                            "methods": ["GET"],
                            "handler_hint": "backend/orders/views.py:order_list",
                        },
                        {
                            "path": "/api/orders/{order_id}/actions/",
                            "methods": ["POST"],
                            "handler_hint": "backend/orders/views.py:order_action",
                        },
                    ],
                    "treat_api_view_as_method_source": True,
                }
            },
            stop=False,
        ),
    )

    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2-analysis-override-rerun",
        llm_provider="openai",
        llm_model="gpt-5-mini",
        chatbot_server_base_url="http://localhost:8100",
    )

    assert result["status"] == "exported"
    assert planning_calls["count"] == 2
    assert captured_analysis_overrides[0] == {}
    assert captured_analysis_overrides[1] == {
        "force_verify_endpoints": [
            {
                "path": "/api/orders/",
                "methods": ["GET"],
                "handler_hint": "backend/orders/views.py:order_list",
            },
            {
                "path": "/api/orders/{order_id}/actions/",
                "methods": ["POST"],
                "handler_hint": "backend/orders/views.py:order_action",
            },
        ],
        "treat_api_view_as_method_source": True,
    }


def test_build_retrieval_smoke_payload_skips_disabled_corpus():
    retrieval_plan = RetrievalIndexPlan(
        site_id="food",
        site_slug="food",
        corpora=[
            RagCorpusPlan(
                corpus="policy",
                enabled=True,
                chunking_strategy="heading_sections",
                collection_alias="site_food__policy",
                build_collection="site_food__policy__run_demo",
                sources=["policy.md"],
                smoke_queries=["환불"],
                minimum_expected_documents=1,
                loader_strategy="policy_source_scan",
            ),
            RagCorpusPlan(
                corpus="discovery_image",
                enabled=False,
                chunking_strategy="product_image_rows",
                collection_alias="site_food__discovery_image",
                build_collection="site_food__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
            ),
        ],
    )

    payload = _build_retrieval_smoke_payload(
        retrieval_plan=retrieval_plan,
        indexing_result={
            "corpora": {
                "policy": {
                    "status": "completed",
                    "enabled": True,
                    "documents_indexed": 12,
                    "smoke_passed": True,
                },
                "discovery_image": {
                    "status": "skipped",
                    "enabled": False,
                    "documents_indexed": 0,
                    "reason": "no_product_rows",
                    "smoke_passed": False,
                },
            }
        },
    )

    results = {item["corpus"]: item for item in payload["results"]}

    assert payload["passed"] is True
    assert results["policy"]["status"] == "passed"
    assert results["policy"]["passed"] is True
    assert results["discovery_image"]["status"] == "skipped"
    assert results["discovery_image"]["passed"] is True
    assert results["discovery_image"]["summary"] == "discovery_image retrieval smoke skipped"
