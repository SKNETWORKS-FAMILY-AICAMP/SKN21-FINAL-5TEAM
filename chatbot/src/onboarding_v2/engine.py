from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event as ThreadingEvent
from typing import Any

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.compile.preflight import (
    CompilePreflightResult,
    run_chatbot_compile_preflight,
    run_flask_host_import_smoke,
)
from chatbot.src.onboarding_v2.eventing import EventCallback, ProgressHeartbeat
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.indexing import HostExportContext, execute_indexing_plan
from chatbot.src.onboarding_v2.models import (
    AnalysisBundle,
    AnalysisSnapshot,
    ApplyResult,
    ArtifactRef,
    EditProgram,
    IntegrationPlan,
    PlanningBundle,
    ReplayResult,
)
from chatbot.src.onboarding_v2.models.common import DebugRecord
from chatbot.src.onboarding_v2.models.repair import RepairDecision
from chatbot.src.onboarding_v2.models.validation import ValidationBundle
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding_v2.repair import (
    collect_file_samples,
    diagnose_failure,
    synthesize_failure,
)
from chatbot.src.onboarding_v2.storage import (
    STAGE_DIRECTORY_MAP,
    ArtifactStore,
    DebugStore,
    EventStore,
    LlmUsageStore,
    RunStore,
    ViewProjector,
)
from chatbot.src.onboarding_v2.validation.runner import (
    ValidationRunResult,
    run_validation_cycle,
)
from chatbot.src.onboarding_v2.validation.backend_runtime import _choose_backend_entrypoint
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


@dataclass(slots=True)
class _RunState:
    analysis_bundle: AnalysisBundle | None = None
    snapshot: AnalysisSnapshot | None = None
    analysis_bundle_ref: ArtifactRef | None = None
    analysis_ref: ArtifactRef | None = None
    planning_bundle: PlanningBundle | None = None
    plan: IntegrationPlan | None = None
    planning_bundle_ref: ArtifactRef | None = None
    plan_ref: ArtifactRef | None = None
    edit_program: EditProgram | None = None
    compile_ref: ArtifactRef | None = None
    chatbot_compile_ref: ArtifactRef | None = None
    compile_preflight_ref: ArtifactRef | None = None
    compile_preflight_result: CompilePreflightResult | None = None
    host_import_smoke_ref: ArtifactRef | None = None
    host_import_smoke_result: CompilePreflightResult | None = None
    apply_result: ApplyResult | None = None
    apply_ref: ArtifactRef | None = None
    patch_ref: ArtifactRef | None = None
    chatbot_patch_ref: ArtifactRef | None = None
    replay_result: ReplayResult | None = None
    replay_ref: ArtifactRef | None = None
    export_bundle_ref: ArtifactRef | None = None
    validation_run: ValidationRunResult | None = None
    prep_ref: ArtifactRef | None = None
    state_ref: ArtifactRef | None = None
    chatbot_runtime_boot_ref: ArtifactRef | None = None
    widget_bundle_fetch_ref: ArtifactRef | None = None
    host_auth_ref: ArtifactRef | None = None
    chatbot_adapter_auth_ref: ArtifactRef | None = None
    widget_order_ref: ArtifactRef | None = None
    fixture_manifest_ref: ArtifactRef | None = None
    conversation_validation_ref: ArtifactRef | None = None
    conversation_transcript_refs: list[ArtifactRef] = field(default_factory=list)
    retrieval_source_manifest_ref: ArtifactRef | None = None
    indexing_plan_ref: ArtifactRef | None = None
    indexing_result_ref: ArtifactRef | None = None
    retrieval_smoke_ref: ArtifactRef | None = None
    indexing_result: dict[str, Any] | None = None
    validation_ref: ArtifactRef | None = None
    latest_repair_ref: ArtifactRef | None = None
    latest_failure_signature: str | None = None
    latest_rewind_to: str | None = None
    repair_attempt_count: int = 0
    pending_required_stage_rechecks: list[str] = field(default_factory=list)
    pending_required_rechecks: list[str] = field(default_factory=list)
    pending_preserve_artifacts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _StageFailure(Exception):
    stage: str
    failure_signature: str
    failure_summary: str
    trigger_event_id: str
    related_artifacts: list[ArtifactRef]
    related_files: list[str]
    input_artifact_versions: dict[str, int]
    workspace_root: str | Path | None = None
    payload: dict[str, Any] | None = None


def _build_stage_event_callback(
    *,
    event_store: EventStore,
    run_id: str,
    stage: str,
    attempt: int,
    actor: str = "system",
    source: str = "deterministic",
    input_refs: list[ArtifactRef] | None = None,
) -> EventCallback:
    default_input_refs = list(input_refs or [])

    def _callback(payload: dict[str, Any]) -> None:
        record_payload = dict(payload)
        record_payload.setdefault("run_id", run_id)
        record_payload.setdefault("stage", stage)
        record_payload.setdefault("attempt", attempt)
        record_payload.setdefault("actor", actor)
        record_payload.setdefault("source", source)
        if default_input_refs and "input_refs" not in record_payload:
            record_payload["input_refs"] = list(default_input_refs)
        event_store.write_event(**record_payload)

    return _callback


def run_onboarding_generation_v2(
    *,
    site: str,
    source_root: str,
    generated_root: str,
    runtime_root: str,
    run_id: str,
    agent_version: str = "dev",
    onboarding_credentials: dict[str, str] | None = None,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini",
    analysis_llm_provider: str | None = None,
    analysis_llm_model: str | None = None,
    planning_llm_provider: str | None = None,
    planning_llm_model: str | None = None,
    analysis_llm_builder: Any | None = None,
    planning_llm_builder: Any | None = None,
    chatbot_server_base_url: str | None = None,
    max_repair_attempts: int = 4,
    **_: Any,
) -> dict[str, Any]:
    max_repair_attempts = max(1, int(max_repair_attempts))
    run_root = Path(generated_root) / site / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    event_store = EventStore(run_root)
    artifact_store = ArtifactStore(run_root)
    debug_store = DebugStore(run_root)
    usage_store = LlmUsageStore(run_root)
    run_store = RunStore(run_root)
    view_projector = ViewProjector(run_root)
    run_store.write_run_metadata(
        site=site,
        source_root=source_root,
        run_id=run_id,
        agent_version=agent_version,
    )
    run_store.write_manifest(
        site=site,
        source_root=source_root,
        run_id=run_id,
        credentials=onboarding_credentials or {},
    )

    state = _RunState()
    next_stage = "analysis"
    analysis_overrides: dict[str, Any] = {}
    planning_overrides: dict[str, Any] = {}
    repeated_failures: dict[str, int] = {}
    final_status = "failed_human_review"
    chatbot_source_root = str(Path(__file__).resolve().parents[2])

    while True:
        attempt = state.repair_attempt_count + 1
        try:
            _run_from_stage(
                start_stage=next_stage,
                state=state,
                site=site,
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                chatbot_server_base_url=chatbot_server_base_url,
                runtime_root=runtime_root,
                run_id=run_id,
                run_root=run_root,
                event_store=event_store,
                artifact_store=artifact_store,
                onboarding_credentials=onboarding_credentials,
                attempt=attempt,
                analysis_overrides=analysis_overrides,
                planning_overrides=planning_overrides,
                debug_store=debug_store,
                usage_store=usage_store,
                analysis_llm_provider=str(analysis_llm_provider or llm_provider),
                analysis_llm_model=str(analysis_llm_model or llm_model),
                planning_llm_provider=str(planning_llm_provider or llm_provider),
                planning_llm_model=str(planning_llm_model or llm_model),
                analysis_llm_builder=analysis_llm_builder,
                planning_llm_builder=planning_llm_builder,
            )
            final_status = "exported"
            break
        except _StageFailure as failure:
            repeat_count = repeated_failures.get(failure.failure_signature, 0) + 1
            repeated_failures = {failure.failure_signature: repeat_count}
            failure_bundle = synthesize_failure(
                failed_stage=failure.stage,
                failure_signature=failure.failure_signature,
                failure_summary=failure.failure_summary,
                trigger_event_id=failure.trigger_event_id,
                related_artifacts=failure.related_artifacts,
                related_files=failure.related_files,
                workspace_root=failure.workspace_root,
                input_artifact_versions=failure.input_artifact_versions,
                attempt_number=attempt,
                repeat_count=repeat_count,
            )
            failure_event = event_store.write_event(
                run_id=run_id,
                stage="repair",
                phase="synthesis",
                event_type="failure_synthesized",
                summary=f"{failure.stage} failure synthesized",
                details={"failed_stage": failure.stage},
                failure_signature=failure.failure_signature,
                attempt=attempt,
                artifact_refs=failure.related_artifacts,
                source="deterministic",
            )
            failure_ref = artifact_store.write_json_artifact(
                stage="repair",
                artifact_type="failure-bundle",
                payload=failure_bundle.model_dump(mode="json"),
                producer="repair",
                input_artifact_refs=failure.related_artifacts,
                event_ref=failure_event.event_id,
                status="failed",
                attempt=attempt,
            )
            state.latest_failure_signature = failure.failure_signature

            event_store.write_event(
                run_id=run_id,
                stage="repair",
                phase="diagnosis_start",
                event_type="repair_diagnosis_started",
                summary="repair diagnosis started",
                input_refs=[failure_ref],
                failure_signature=failure.failure_signature,
                attempt=attempt,
                actor="repair_agent",
                source="llm",
            )
            repair_event_callback = _build_stage_event_callback(
                event_store=event_store,
                run_id=run_id,
                stage="repair",
                attempt=attempt,
                actor="repair_agent",
                input_refs=[failure_ref],
            )
            decision = diagnose_failure(
                failure_bundle=failure_bundle,
                analysis_bundle_payload=(
                    {}
                    if state.analysis_bundle is None
                    else state.analysis_bundle.model_dump(mode="json")
                ),
                snapshot_payload=(
                    {} if state.snapshot is None else state.snapshot.model_dump(mode="json")
                ),
                planning_bundle_payload=(
                    {}
                    if state.planning_bundle is None
                    else state.planning_bundle.model_dump(mode="json")
                ),
                plan_payload={} if state.plan is None else state.plan.model_dump(mode="json"),
                edit_program_payload=(
                    {} if state.edit_program is None else state.edit_program.model_dump(mode="json")
                ),
                validation_payload=_failure_validation_payload(state),
                llm_provider=llm_provider,
                llm_model=llm_model,
                debug_store=debug_store,
                event_callback=repair_event_callback,
            )
            if decision.additional_discovery:
                discovery_paths = [
                    str(item.get("path") or "").strip()
                    for item in decision.additional_discovery
                    if str(item.get("path") or "").strip()
                ][:5]
                if discovery_paths:
                    event_store.write_event(
                        run_id=run_id,
                        stage="repair",
                        phase="discovery_start",
                        event_type="repair_additional_discovery_started",
                        summary="repair additional discovery started",
                        input_refs=[failure_ref],
                        failure_signature=failure.failure_signature,
                        attempt=attempt,
                        actor="repair_agent",
                        source="deterministic",
                    )
                    discovery_heartbeat = ProgressHeartbeat(
                        event_callback=repair_event_callback,
                        phase="discovery_progress",
                        event_type="repair_additional_discovery_progress",
                        summary="repair additional discovery still running",
                        details_factory=lambda elapsed_ms: {
                            "discovered_paths": discovery_paths,
                            "elapsed_ms": elapsed_ms,
                            "status": "running",
                        },
                    ).start()
                    try:
                        extra_samples = collect_file_samples(
                            workspace_root=_resolve_workspace_root(source_root=source_root, state=state),
                            related_files=discovery_paths,
                        )
                    finally:
                        discovery_heartbeat.stop()
                    failure_bundle = failure_bundle.model_copy(
                        update={
                            "related_files": list(
                                dict.fromkeys(failure_bundle.related_files + discovery_paths)
                            ),
                            "related_file_samples": failure_bundle.related_file_samples
                            + extra_samples,
                        }
                    )
                    event_store.write_event(
                        run_id=run_id,
                        stage="repair",
                        phase="discovery_finish",
                        event_type="repair_additional_discovery_completed",
                        summary="repair additional discovery completed",
                        details={"discovered_paths": discovery_paths},
                        failure_signature=failure.failure_signature,
                        attempt=attempt,
                        actor="repair_agent",
                        source="deterministic",
                    )
                    decision = diagnose_failure(
                        failure_bundle=failure_bundle,
                        analysis_bundle_payload=(
                            {}
                            if state.analysis_bundle is None
                            else state.analysis_bundle.model_dump(mode="json")
                        ),
                        snapshot_payload=(
                            {} if state.snapshot is None else state.snapshot.model_dump(mode="json")
                        ),
                        planning_bundle_payload=(
                            {}
                            if state.planning_bundle is None
                            else state.planning_bundle.model_dump(mode="json")
                        ),
                        plan_payload=(
                            {} if state.plan is None else state.plan.model_dump(mode="json")
                        ),
                        edit_program_payload=(
                            {}
                            if state.edit_program is None
                            else state.edit_program.model_dump(mode="json")
                        ),
                        validation_payload=_failure_validation_payload(state),
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        debug_store=debug_store,
                        event_callback=repair_event_callback,
                    )

            if repeat_count >= max_repair_attempts:
                decision = decision.model_copy(
                    update={"stop": True, "stop_reason": "repeated_failure_signature"}
                )

            requested_rewind_to = decision.rewind_to
            effective_rewind_to = _derive_effective_rewind_to(decision)
            normalized_rechecks = _normalize_required_rechecks(decision.required_rechecks)
            decision_payload = decision.model_dump(mode="json")
            decision_payload["requested_rewind_to"] = requested_rewind_to
            decision_payload["effective_rewind_to"] = effective_rewind_to
            decision_payload["requested_required_rechecks"] = list(decision.required_rechecks)
            decision_payload["required_stage_rechecks"] = list(normalized_rechecks["stage_rechecks"])
            decision_payload["required_check_rechecks"] = list(normalized_rechecks["check_rechecks"])
            decision_payload["ignored_required_rechecks"] = list(normalized_rechecks["ignored_rechecks"])

            decision_event = event_store.write_event(
                run_id=run_id,
                stage="repair",
                phase="decision",
                event_type="repair_decision_emitted",
                summary="repair decision emitted",
                input_refs=[failure_ref],
                failure_signature=decision.failure_signature,
                rewind_to=effective_rewind_to,
                requested_rewind_to=requested_rewind_to,
                effective_rewind_to=effective_rewind_to,
                attempt=attempt,
                actor="repair_agent",
                source="llm",
            )
            decision_ref = artifact_store.write_json_artifact(
                stage="repair",
                artifact_type="repair-decision",
                payload=decision_payload,
                producer="repair",
                input_artifact_refs=[failure_ref],
                event_ref=decision_event.event_id,
                status="completed" if not decision.stop else "failed",
                attempt=attempt,
            )
            debug_store.write_record(
                stage="repair",
                label="effective-rewind",
                record=DebugRecord(
                    stage="repair",
                    attempt=attempt,
                    prompt={
                        "failure_signature": decision.failure_signature,
                        "artifact_overrides": decision.artifact_overrides,
                    },
                    normalized_response=decision_payload,
                    parse_result={"status": "derived"},
                    artifact_refs=[failure_ref],
                    event_ref=decision_event.event_id,
                    requested_rewind_to=requested_rewind_to,
                    effective_rewind_to=effective_rewind_to,
                ),
            )
            state.latest_repair_ref = decision_ref
            state.latest_rewind_to = effective_rewind_to
            state.repair_attempt_count = attempt

            if decision.stop:
                event_store.write_event(
                    run_id=run_id,
                    stage="repair",
                    phase="stop",
                    event_type="repair_stopped",
                    summary="repair stopped",
                    input_refs=[failure_ref, decision_ref],
                    failure_signature=decision.failure_signature,
                    rewind_to=effective_rewind_to,
                    requested_rewind_to=requested_rewind_to,
                    effective_rewind_to=effective_rewind_to,
                    details={"stop_reason": decision.stop_reason},
                    attempt=attempt,
                    actor="repair_agent",
                    source="llm",
                )
                final_status = "failed_human_review"
                break

            event_store.write_event(
                run_id=run_id,
                stage="repair",
                phase="rewind",
                event_type="rewind_requested",
                summary=f"rewind requested to {requested_rewind_to} (effective {effective_rewind_to})",
                input_refs=[failure_ref, decision_ref],
                failure_signature=decision.failure_signature,
                rewind_to=effective_rewind_to,
                requested_rewind_to=requested_rewind_to,
                effective_rewind_to=effective_rewind_to,
                attempt=attempt,
                actor="repair_agent",
                source="llm",
            )
            _clear_state_for_failure(
                state=state,
                failed_stage=failure.stage,
                rewind_to=effective_rewind_to,
                preserve_artifacts=decision.preserve_artifacts,
            )
            state.pending_required_stage_rechecks = list(normalized_rechecks["stage_rechecks"])
            state.pending_required_rechecks = list(normalized_rechecks["check_rechecks"])
            state.pending_preserve_artifacts = list(dict.fromkeys(decision.preserve_artifacts))
            analysis_overrides = dict(decision.artifact_overrides.get("analysis") or {})
            planning_overrides = dict(decision.artifact_overrides.get("planning") or {})
            next_stage = effective_rewind_to
            event_store.write_event(
                run_id=run_id,
                stage=next_stage,
                phase="rerun",
                event_type="stage_rerun_started",
                summary=f"{next_stage} rerun started",
                failure_signature=decision.failure_signature,
                rewind_to=effective_rewind_to,
                requested_rewind_to=requested_rewind_to,
                effective_rewind_to=effective_rewind_to,
                attempt=attempt + 1,
                actor="repair_agent",
                source="deterministic",
            )

    llm_usage_ref = _write_llm_usage_summary_artifact(
        artifact_store=artifact_store,
        usage_store=usage_store,
        analysis_ref=state.analysis_ref,
        plan_ref=state.plan_ref,
        attempt=attempt,
    )
    view_projector.project(
        run_id=run_id,
        site=site,
        status=final_status,
        latest_failure_signature=state.latest_failure_signature,
        latest_rewind_to=state.latest_rewind_to,
        repair_attempt_count=state.repair_attempt_count,
        stopped_for_review=final_status == "failed_human_review",
        retrieval_status=dict((state.indexing_result or {}).get("corpora") or {}),
        final_capability_profile=(
            None if state.plan is None else state.plan.host_backend.capability_profile
        ),
        enabled_retrieval_corpora=(
            [] if state.plan is None else list(state.plan.host_backend.enabled_retrieval_corpora)
        ),
    )
    return {
        "engine": "v2",
        "run_root": str(run_root),
        "status": final_status,
        "runtime_workspace": None if state.apply_result is None else state.apply_result.workspace_path,
        "host_runtime_workspace": None
        if state.apply_result is None
        else state.apply_result.host_workspace_path,
        "chatbot_runtime_workspace": None
        if state.apply_result is None
        else state.apply_result.chatbot_workspace_path,
        "latest_analysis_artifact": _artifact_abspath(run_root, state.analysis_ref),
        "latest_analysis_bundle_artifact": _artifact_abspath(run_root, state.analysis_bundle_ref),
        "latest_plan_artifact": _artifact_abspath(run_root, state.plan_ref),
        "latest_planning_bundle_artifact": _artifact_abspath(run_root, state.planning_bundle_ref),
        "latest_compile_artifact": _artifact_abspath(run_root, state.compile_ref),
        "latest_chatbot_compile_artifact": _artifact_abspath(
            run_root, state.chatbot_compile_ref
        ),
        "latest_compile_preflight_artifact": _artifact_abspath(
            run_root, state.compile_preflight_ref
        ),
        "compile_preflight_result": None
        if state.compile_preflight_result is None
        else state.compile_preflight_result.model_dump(mode="json"),
        "latest_host_import_smoke_artifact": _artifact_abspath(
            run_root, state.host_import_smoke_ref
        ),
        "host_import_smoke_result": None
        if state.host_import_smoke_result is None
        else state.host_import_smoke_result.model_dump(mode="json"),
        "latest_apply_artifact": _artifact_abspath(run_root, state.apply_ref),
        "latest_validation_artifact": _artifact_abspath(run_root, state.validation_ref),
        "latest_export_artifact": _artifact_abspath(run_root, state.export_bundle_ref),
        "latest_indexing_artifact": _artifact_abspath(run_root, state.indexing_result_ref),
        "latest_llm_usage_artifact": _artifact_abspath(run_root, llm_usage_ref),
        "approved_patch_path": _artifact_abspath(run_root, state.patch_ref),
        "chatbot_approved_patch_path": _artifact_abspath(
            run_root, state.chatbot_patch_ref
        ),
        "latest_replay_artifact": _artifact_abspath(run_root, state.replay_ref),
        "latest_repair_artifact": _artifact_abspath(run_root, state.latest_repair_ref),
        "repair_attempt_count": state.repair_attempt_count,
        "failure_signature": state.latest_failure_signature,
    }


def _run_from_stage(
    *,
    start_stage: str,
    state: _RunState,
    site: str,
    source_root: str,
    chatbot_source_root: str,
    chatbot_server_base_url: str | None,
    runtime_root: str,
    run_id: str,
    run_root: Path,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    onboarding_credentials: dict[str, str] | None,
    attempt: int,
    analysis_overrides: dict[str, Any],
    planning_overrides: dict[str, Any],
    debug_store: DebugStore,
    usage_store: LlmUsageStore,
    analysis_llm_provider: str,
    analysis_llm_model: str,
    planning_llm_provider: str,
    planning_llm_model: str,
    analysis_llm_builder: Any | None,
    planning_llm_builder: Any | None,
) -> None:
    if start_stage == "analysis":
        run_analysis_stage(
            site=site,
            source_root=source_root,
            run_id=run_id,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            attempt=attempt,
            overrides=analysis_overrides,
            debug_store=debug_store,
            usage_store=usage_store,
            llm_provider=analysis_llm_provider,
            llm_model=analysis_llm_model,
            llm_builder=analysis_llm_builder,
        )
        analysis_overrides.clear()
        start_stage = "planning"

    if start_stage == "planning":
        run_planning_stage(
            run_id=run_id,
            chatbot_server_base_url=chatbot_server_base_url,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            attempt=attempt,
            overrides=planning_overrides,
            debug_store=debug_store,
            usage_store=usage_store,
            llm_provider=planning_llm_provider,
            llm_model=planning_llm_model,
            llm_builder=planning_llm_builder,
        )
        planning_overrides.clear()
        start_stage = "compile"

    if start_stage in {"compile", "apply", "export"}:
        _run_parallel_execution_lanes(
            start_stage=start_stage,
            source_root=source_root,
            chatbot_source_root=chatbot_source_root,
            runtime_root=runtime_root,
            run_root=run_root,
            site=site,
            run_id=run_id,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            attempt=attempt,
        )
        start_stage = "validation"

    if start_stage == "indexing":
        run_indexing_stage(
            site=site,
            source_root=source_root,
            run_id=run_id,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            attempt=attempt,
        )
        start_stage = "validation"

    if start_stage == "validation":
        if state.apply_result is None or state.apply_ref is None:
            run_apply_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                runtime_root=runtime_root,
                site=site,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
        if state.replay_result is None or state.replay_ref is None:
            run_export_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                runtime_root=runtime_root,
                run_root=run_root,
                site=site,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
        if (
            state.indexing_result is None
            and state.plan is not None
            and state.plan_ref is not None
        ):
            run_indexing_stage(
                site=site,
                source_root=source_root,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
        run_validation_stage(
            run_root=run_root,
            run_id=run_id,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            onboarding_credentials=onboarding_credentials,
            attempt=attempt,
        )


def run_analysis_stage(
    *,
    site: str,
    source_root: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
    overrides: dict[str, Any],
    debug_store: DebugStore,
    usage_store: LlmUsageStore,
    llm_provider: str,
    llm_model: str,
    llm_builder: Any | None,
) -> None:
    started = event_store.write_event(
        run_id=run_id,
        stage="analysis",
        phase="start",
        event_type="stage_started",
        summary="analysis started",
        attempt=attempt,
    )
    try:
        analysis_event_callback = _build_stage_event_callback(
            event_store=event_store,
            run_id=run_id,
            stage="analysis",
            attempt=attempt,
        )
        analysis_bundle = build_analysis_bundle(
            site=site,
            source_root=source_root,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_builder=llm_builder,
            debug_store=debug_store,
            usage_store=usage_store,
            attempt=attempt,
            overrides=overrides,
            event_callback=analysis_event_callback,
        )
        snapshot = analysis_bundle.snapshot
        snapshot = _apply_analysis_overrides(snapshot=snapshot, overrides=overrides)
        analysis_bundle = analysis_bundle.model_copy(update={"snapshot": snapshot})
        analysis_bundle_ref = artifact_store.write_json_artifact(
            stage="analysis",
            artifact_type="analysis-bundle",
            payload=analysis_bundle.model_dump(mode="json"),
            producer="analyzer",
            event_ref=started.event_id,
            attempt=attempt,
            provenance={
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "phase_owners": {
                    "repo_boundary_scan": "deterministic",
                    "framework_fingerprint": "deterministic",
                    "retrieval_plan": "llm_assisted",
                    "candidate_harvest": "deterministic",
                    "evidence_reading": "llm_assisted",
                    "contract_extraction": "llm_assisted",
                    "contract_verification": "deterministic",
                    "analysis_graph": "deterministic",
                },
                "unresolved_ambiguities": list(analysis_bundle.unresolved_ambiguities),
                "confidence_notes": list(analysis_bundle.framework_profile.confidence_notes),
                "repair_override_applied": bool(overrides),
                "repair_overrides": dict(overrides),
                "required_rechecks": _combined_pending_required_rechecks(state),
                "required_stage_rechecks": list(state.pending_required_stage_rechecks),
                "required_check_rechecks": list(state.pending_required_rechecks),
            },
        )
        analysis_ref = artifact_store.write_json_artifact(
            stage="analysis",
            artifact_type="snapshot",
            payload=snapshot.model_dump(mode="json"),
            producer="analyzer",
            event_ref=started.event_id,
            attempt=attempt,
            input_artifact_refs=[analysis_bundle_ref],
            provenance={
                "derived_from": "analysis-bundle",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "unresolved_ambiguities": list(analysis_bundle.unresolved_ambiguities),
            },
        )
        event_store.write_event(
            run_id=run_id,
            stage="analysis",
            phase="finish",
            event_type="stage_completed",
            summary="analysis completed",
            artifact_refs=[analysis_bundle_ref, analysis_ref],
            attempt=attempt,
        )
        state.analysis_bundle = analysis_bundle
        state.analysis_bundle_ref = analysis_bundle_ref
        state.snapshot = snapshot
        state.analysis_ref = analysis_ref
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["analysis"])
    except Exception as exc:
        failure_signature = build_failure_signature(check_name="analysis", summary=str(exc))
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="analysis",
            phase="finish",
            event_type="stage_failed",
            summary="analysis failed",
            details={"error": str(exc)},
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="analysis",
            failure_signature=failure_signature,
            failure_summary=str(exc),
            trigger_event_id=failed_event.event_id,
            related_artifacts=[],
            related_files=[],
            input_artifact_versions={},
            workspace_root=source_root,
            payload={"error": str(exc)},
        )


def run_planning_stage(
    *,
    run_id: str,
    chatbot_server_base_url: str | None,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
    overrides: dict[str, Any],
    debug_store: DebugStore,
    usage_store: LlmUsageStore,
    llm_provider: str,
    llm_model: str,
    llm_builder: Any | None,
) -> None:
    if state.snapshot is None or state.analysis_ref is None or state.analysis_bundle is None:
        raise ValueError("analysis snapshot is required before planning")
    previous_retrieval_plan = None if state.plan is None else state.plan.retrieval_index_plan
    started = event_store.write_event(
        run_id=run_id,
        stage="planning",
        phase="start",
        event_type="stage_started",
        summary="planning started",
        input_refs=[state.analysis_ref],
        attempt=attempt,
    )
    try:
        planning_event_callback = _build_stage_event_callback(
            event_store=event_store,
            run_id=run_id,
            stage="planning",
            attempt=attempt,
            input_refs=[state.analysis_ref],
        )
        planning_bundle = build_planning_bundle(
            snapshot=state.snapshot,
            analysis_bundle=state.analysis_bundle,
            chatbot_server_base_url=str(chatbot_server_base_url or ""),
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_builder=llm_builder,
            debug_store=debug_store,
            usage_store=usage_store,
            attempt=attempt,
            artifact_refs=[state.analysis_ref],
            event_callback=planning_event_callback,
        )
        plan = planning_bundle.integration_plan
        plan = _apply_planning_overrides(plan=plan, overrides=overrides)
        planning_bundle = planning_bundle.model_copy(update={"integration_plan": plan})
        planning_bundle_ref = artifact_store.write_json_artifact(
            stage="planning",
            artifact_type="planning-bundle",
            payload=planning_bundle.model_dump(mode="json"),
            producer="planner",
            input_artifact_refs=[state.analysis_bundle_ref or state.analysis_ref],
            event_ref=started.event_id,
            attempt=attempt,
            provenance={
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "phase_owners": {
                    "goal_materialization": "deterministic",
                    "coverage_check": "deterministic",
                    "strategy_synthesis": "llm_assisted",
                    "feasibility_filter": "deterministic",
                    "binding_selection": "llm_assisted",
                    "operation_ir": "deterministic",
                    "validation_plan": "deterministic",
                    "risk_register": "llm_assisted",
                    "repair_hints": "llm_assisted",
                },
                "coverage": planning_bundle.coverage_report.model_dump(mode="json"),
                "repair_override_applied": bool(overrides),
                "repair_overrides": dict(overrides),
                "required_rechecks": _combined_pending_required_rechecks(state),
                "required_stage_rechecks": list(state.pending_required_stage_rechecks),
                "required_check_rechecks": list(state.pending_required_rechecks),
            },
        )
        plan_ref = artifact_store.write_json_artifact(
            stage="planning",
            artifact_type="integration-plan",
            payload=plan.model_dump(mode="json"),
            producer="planner",
            input_artifact_refs=[planning_bundle_ref],
            event_ref=started.event_id,
            attempt=attempt,
            provenance={
                "derived_from": "planning-bundle",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "coverage": planning_bundle.coverage_report.model_dump(mode="json"),
            },
        )
        event_store.write_event(
            run_id=run_id,
            stage="planning",
            phase="finish",
            event_type="stage_completed",
            summary="planning completed",
            artifact_refs=[planning_bundle_ref, plan_ref],
            input_refs=[state.analysis_ref],
            attempt=attempt,
        )
        state.planning_bundle = planning_bundle
        state.planning_bundle_ref = planning_bundle_ref
        state.plan = plan
        state.plan_ref = plan_ref
        _reconcile_preserved_indexing_after_planning(
            state=state,
            previous_retrieval_plan=previous_retrieval_plan,
        )
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["planning"])
    except Exception as exc:
        failure_signature = build_failure_signature(check_name="planning", summary=str(exc))
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="planning",
            phase="finish",
            event_type="stage_failed",
            summary="planning failed",
            details={"error": str(exc)},
            input_refs=[] if state.analysis_ref is None else [state.analysis_ref],
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="planning",
            failure_signature=failure_signature,
            failure_summary=str(exc),
            trigger_event_id=failed_event.event_id,
            related_artifacts=[] if state.analysis_ref is None else [state.analysis_ref],
            related_files=[],
            input_artifact_versions=_artifact_versions(state),
            workspace_root=state.snapshot.repo_profile.source_root,
            payload={"error": str(exc)},
        )


def run_compile_stage(
    *,
    source_root: str,
    chatbot_source_root: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
) -> None:
    if (
        state.analysis_bundle is None
        or state.snapshot is None
        or state.analysis_ref is None
        or state.planning_bundle is None
        or state.plan is None
        or state.plan_ref is None
    ):
        raise ValueError("analysis bundle, snapshot, planning bundle, and plan are required before compile")
    started = event_store.write_event(
        run_id=run_id,
        stage="compile",
        phase="start",
        event_type="stage_started",
        summary="compile started",
        input_refs=[state.analysis_ref, state.plan_ref],
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="compile",
        phase="chatbot_bridge_start",
        event_type="chatbot_bridge_compile_started",
        summary="chatbot bridge compile started",
        input_refs=[state.analysis_ref, state.plan_ref],
        attempt=attempt,
    )
    try:
        edit_program = compile_plan(
            analysis_bundle=state.analysis_bundle,
            planning_bundle=state.planning_bundle,
            source_root=source_root,
            chatbot_source_root=chatbot_source_root,
        )
        compile_ref = artifact_store.write_json_artifact(
            stage="compile",
            artifact_type="host-edit-program",
            payload=edit_program.host_program.model_dump(mode="json"),
            producer="compiler",
            input_artifact_refs=[state.analysis_ref, state.plan_ref],
            event_ref=started.event_id,
            attempt=attempt,
        )
        chatbot_compile_ref = artifact_store.write_json_artifact(
            stage="compile",
            artifact_type="chatbot-edit-program",
            payload=edit_program.chatbot_program.model_dump(mode="json"),
            producer="compiler",
            input_artifact_refs=[state.analysis_ref, state.plan_ref],
            event_ref=started.event_id,
            attempt=attempt,
        )
        event_store.write_event(
            run_id=run_id,
            stage="compile",
            phase="chatbot_bridge_finish",
            event_type="chatbot_bridge_compile_completed",
            summary="chatbot bridge compile completed",
            artifact_refs=[chatbot_compile_ref],
            input_refs=[state.analysis_ref, state.plan_ref],
            attempt=attempt,
        )
        event_store.write_event(
            run_id=run_id,
            stage="compile",
            phase="finish",
            event_type="stage_completed",
            summary="compile completed",
            artifact_refs=[compile_ref, chatbot_compile_ref],
            input_refs=[state.analysis_ref, state.plan_ref],
            attempt=attempt,
        )
        state.edit_program = edit_program
        state.compile_ref = compile_ref
        state.chatbot_compile_ref = chatbot_compile_ref
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["compile"])
    except Exception as exc:
        failure_signature = build_failure_signature(check_name="compile", summary=str(exc))
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="compile",
            phase="finish",
            event_type="stage_failed",
            summary="compile failed",
            details={"error": str(exc)},
            input_refs=[state.analysis_ref, state.plan_ref],
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="compile",
            failure_signature=failure_signature,
            failure_summary=str(exc),
            trigger_event_id=failed_event.event_id,
            related_artifacts=[state.analysis_ref, state.plan_ref],
            related_files=_related_compile_files(state.plan),
            input_artifact_versions=_artifact_versions(state),
            workspace_root=source_root,
            payload={"error": str(exc)},
        )


def run_apply_stage(
    *,
    source_root: str,
    chatbot_source_root: str,
    runtime_root: str,
    site: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
) -> None:
    if state.edit_program is None or state.compile_ref is None or state.chatbot_compile_ref is None:
        raise ValueError("edit program is required before apply")
    started = event_store.write_event(
        run_id=run_id,
        stage="apply",
        phase="start",
        event_type="stage_started",
        summary="apply started",
        input_refs=[state.compile_ref, state.chatbot_compile_ref],
        attempt=attempt,
    )
    try:
        apply_result = apply_edit_program(
            host_source_root=source_root,
            chatbot_source_root=chatbot_source_root,
            runtime_root=runtime_root,
            site=site,
            run_id=run_id,
            edit_program=state.edit_program,
        )
        apply_ref = artifact_store.write_json_artifact(
            stage="apply",
            artifact_type="apply-result",
            payload=apply_result.model_dump(mode="json"),
            producer="executor",
            input_artifact_refs=[state.compile_ref, state.chatbot_compile_ref],
            event_ref=started.event_id,
            status="completed" if apply_result.passed else "failed",
            attempt=attempt,
        )
        if not apply_result.passed:
            apply_failure_summary = str(apply_result.failure_summary or "apply failed")
            failure_signature = build_failure_signature(
                check_name="apply",
                summary=apply_failure_summary,
            )
            failed_event = event_store.write_event(
                run_id=run_id,
                stage="apply",
                phase="finish",
                event_type="stage_failed",
                summary=apply_failure_summary,
                details=dict(apply_result.failure_details or {}),
                artifact_refs=[apply_ref],
                input_refs=[state.compile_ref, state.chatbot_compile_ref],
                failure_signature=failure_signature,
                attempt=attempt,
            )
            raise _StageFailure(
                stage="apply",
                failure_signature=failure_signature,
                failure_summary=apply_failure_summary,
                trigger_event_id=failed_event.event_id,
                related_artifacts=[state.compile_ref, state.chatbot_compile_ref, apply_ref],
                related_files=apply_result.applied_files,
                input_artifact_versions=_artifact_versions(state),
                workspace_root=apply_result.workspace_path,
                payload=apply_result.model_dump(mode="json"),
            )
        event_store.write_event(
            run_id=run_id,
            stage="apply",
            phase="finish",
            event_type="stage_completed",
            summary="apply completed",
            artifact_refs=[apply_ref],
            input_refs=[state.compile_ref, state.chatbot_compile_ref],
            attempt=attempt,
        )
        state.apply_result = apply_result
        state.apply_ref = apply_ref
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["apply"])
        run_compile_preflight_stage(
            run_id=run_id,
            state=state,
            event_store=event_store,
            artifact_store=artifact_store,
            attempt=attempt,
        )
    except _StageFailure:
        raise
    except Exception as exc:
        failure_signature = build_failure_signature(check_name="apply", summary=str(exc))
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="apply",
            phase="finish",
            event_type="stage_failed",
            summary="apply failed",
            details={"error": str(exc)},
            input_refs=[state.compile_ref, state.chatbot_compile_ref],
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="apply",
            failure_signature=failure_signature,
            failure_summary=str(exc),
            trigger_event_id=failed_event.event_id,
            related_artifacts=[state.compile_ref, state.chatbot_compile_ref],
            related_files=[],
            input_artifact_versions=_artifact_versions(state),
            workspace_root=source_root,
            payload={"error": str(exc)},
        )


def run_export_stage(
    *,
    source_root: str,
    chatbot_source_root: str,
    runtime_root: str,
    run_root: Path,
    site: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
) -> None:
    if state.apply_result is None or state.apply_ref is None:
        raise ValueError("apply result is required before export")
    started = event_store.write_event(
        run_id=run_id,
        stage="export",
        phase="start",
        event_type="stage_started",
        summary="export replay started",
        input_refs=[state.apply_ref],
        attempt=attempt,
    )
    try:
        export_bundle_ref, replay_result, replay_ref = export_and_replay(
            host_source_root=source_root,
            chatbot_source_root=chatbot_source_root,
            host_baseline_root=state.apply_result.host_source_snapshot_path or source_root,
            chatbot_baseline_root=state.apply_result.chatbot_source_snapshot_path or chatbot_source_root,
            host_runtime_workspace=state.apply_result.host_workspace_path,
            chatbot_runtime_workspace=state.apply_result.chatbot_workspace_path,
            host_allowed_targets=state.apply_result.host_applied_files,
            chatbot_allowed_targets=state.apply_result.chatbot_applied_files,
            runtime_root=runtime_root,
            run_root=run_root,
            site=site,
            run_id=run_id,
            artifact_store=artifact_store,
        )
        host_patch_ref = artifact_store.read_latest_ref(
            stage="export", artifact_type="host-approved.patch"
        )
        chatbot_patch_ref = artifact_store.read_latest_ref(
            stage="export", artifact_type="chatbot-approved.patch"
        )
        if host_patch_ref is None or chatbot_patch_ref is None:
            raise ValueError("dual patch export did not produce both host and chatbot patch artifacts")
        if not replay_result.passed:
            failure_signature = build_failure_signature(
                check_name="export", summary="replay apply failed"
            )
            failed_event = event_store.write_event(
                run_id=run_id,
                stage="export",
                phase="finish",
                event_type="stage_failed",
                summary="export replay failed",
                artifact_refs=[host_patch_ref, chatbot_patch_ref, replay_ref, export_bundle_ref],
                input_refs=[state.apply_ref],
                failure_signature=failure_signature,
                attempt=attempt,
            )
            raise _StageFailure(
                stage="export",
                failure_signature=failure_signature,
                failure_summary="export replay failed",
                trigger_event_id=failed_event.event_id,
                related_artifacts=[
                    state.apply_ref,
                    host_patch_ref,
                    chatbot_patch_ref,
                    replay_ref,
                    export_bundle_ref,
                ],
                related_files=[],
                input_artifact_versions=_artifact_versions(state),
                workspace_root=state.apply_result.workspace_path,
                payload=replay_result.model_dump(mode="json"),
            )
        event_store.write_event(
            run_id=run_id,
            stage="export",
            phase="dual_patch_finish",
            event_type="dual_patch_export_completed",
            summary="dual patch export completed",
            artifact_refs=[host_patch_ref, chatbot_patch_ref],
            input_refs=[state.apply_ref],
            attempt=attempt,
        )
        event_store.write_event(
            run_id=run_id,
            stage="export",
            phase="finish",
            event_type="stage_completed",
            summary="export replay completed",
            artifact_refs=[host_patch_ref, chatbot_patch_ref, replay_ref, export_bundle_ref],
            input_refs=[state.apply_ref],
            attempt=attempt,
        )
        state.patch_ref = host_patch_ref
        state.chatbot_patch_ref = chatbot_patch_ref
        state.replay_result = replay_result
        state.replay_ref = replay_ref
        state.export_bundle_ref = export_bundle_ref
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["export"])
    except _StageFailure:
        raise
    except Exception as exc:
        failure_signature = build_failure_signature(check_name="export", summary=str(exc))
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="export",
            phase="finish",
            event_type="stage_failed",
            summary="export replay failed",
            details={"error": str(exc)},
            input_refs=[state.apply_ref] if state.apply_ref is not None else [],
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="export",
            failure_signature=failure_signature,
            failure_summary=str(exc),
            trigger_event_id=failed_event.event_id,
            related_artifacts=[] if state.apply_ref is None else [state.apply_ref],
            related_files=[],
            input_artifact_versions=_artifact_versions(state),
            workspace_root=None
            if state.apply_result is None
            else state.apply_result.workspace_path,
            payload={"error": str(exc)},
        )


def _run_parallel_execution_lanes(
    *,
    start_stage: str,
    source_root: str,
    chatbot_source_root: str,
    runtime_root: str,
    run_root: Path,
    site: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
) -> None:
    indexing_future = None
    executor = None
    indexing_cancel_event = None
    host_context = None
    indexing_started_event = None
    retrieval_plan = None if state.plan is None else state.plan.retrieval_index_plan
    should_run_indexing = (
        retrieval_plan is not None
        and bool(retrieval_plan.corpora)
        and state.indexing_result is None
        and start_stage in {"compile", "apply", "export"}
    )

    if should_run_indexing:
        indexing_cancel_event = ThreadingEvent()
        host_context = _build_host_export_context(state=state)
        indexing_started_event = event_store.write_event(
            run_id=run_id,
            stage="indexing",
            phase="start",
            event_type="stage_started",
            summary="indexing started",
            input_refs=[ref for ref in [state.analysis_bundle_ref, state.plan_ref] if ref is not None],
            attempt=attempt,
        )
        executor = ThreadPoolExecutor(max_workers=1)
        indexing_future = executor.submit(
            execute_indexing_plan,
            plan=retrieval_plan,
            root=source_root,
            cancel_event=indexing_cancel_event,
            host_context=host_context,
            event_callback=_build_stage_event_callback(
                event_store=event_store,
                run_id=run_id,
                stage="indexing",
                attempt=attempt,
                input_refs=[ref for ref in [state.analysis_bundle_ref, state.plan_ref] if ref is not None],
            ),
        )

    try:
        if start_stage == "compile":
            run_compile_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
            start_stage = "apply"

        if start_stage == "apply":
            run_apply_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                runtime_root=runtime_root,
                site=site,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
            start_stage = "export"

        if start_stage == "export":
            run_export_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                runtime_root=runtime_root,
                run_root=run_root,
                site=site,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
            if host_context is not None:
                _mark_host_export_ready(host_context=host_context, state=state)
                event_store.write_event(
                    run_id=run_id,
                    stage="indexing",
                    phase="host_export_ready",
                    event_type="indexing_host_export_ready",
                    summary="indexing host export ready",
                    input_refs=[ref for ref in [state.apply_ref, state.export_bundle_ref] if ref is not None],
                    attempt=attempt,
                )

        if should_run_indexing:
            indexing_result = (
                {"site_id": site, "site_slug": site, "corpora": {}}
                if indexing_future is None
                else indexing_future.result()
            )
            run_indexing_stage(
                site=site,
                source_root=source_root,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
                precomputed_result=indexing_result,
                started_event=indexing_started_event,
            )
    except Exception:
        if indexing_cancel_event is not None:
            indexing_cancel_event.set()
        if host_context is not None:
            host_context.host_failed.set()
            host_context.export_ready.set()
        if indexing_future is not None:
            try:
                indexing_future.result()
            except Exception:
                pass
        raise
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def run_indexing_stage(
    *,
    site: str,
    source_root: str,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
    precomputed_result: dict[str, Any] | None = None,
    started_event: Any | None = None,
) -> None:
    if state.analysis_bundle is None or state.plan is None or state.plan_ref is None:
        raise ValueError("analysis bundle and plan are required before indexing")
    retrieval_plan = state.plan.retrieval_index_plan
    started = started_event or event_store.write_event(
        run_id=run_id,
        stage="indexing",
        phase="start",
        event_type="stage_started",
        summary="indexing started",
        input_refs=[ref for ref in [state.analysis_bundle_ref, state.plan_ref] if ref is not None],
        attempt=attempt,
    )
    if retrieval_plan is None or not retrieval_plan.corpora:
        empty_result = {"site_id": site, "site_slug": site, "corpora": {}}
        state.indexing_result = empty_result
        state.plan = _apply_indexing_result_to_plan(plan=state.plan, indexing_result=empty_result)
        _mark_required_stage_rechecks_satisfied(state=state, satisfied=["indexing"])
        event_store.write_event(
            run_id=run_id,
            stage="indexing",
            phase="finish",
            event_type="stage_completed",
            summary="indexing skipped because no retrieval corpora were planned",
            attempt=attempt,
        )
        return

    indexing_result = precomputed_result or execute_indexing_plan(
        plan=retrieval_plan,
        root=source_root,
        host_context=_build_host_export_context(state=state, export_ready=True),
        live_logs_root=artifact_store.run_root / "artifacts" / "06-indexing" / "live-logs",
        event_callback=_build_stage_event_callback(
            event_store=event_store,
            run_id=run_id,
            stage="indexing",
            attempt=attempt,
            input_refs=[ref for ref in [state.analysis_bundle_ref, state.plan_ref] if ref is not None],
        ),
    )
    retrieval_status = dict(indexing_result.get("corpora") or {})
    smoke_payload = _build_retrieval_smoke_payload(retrieval_plan=retrieval_plan, indexing_result=indexing_result)

    retrieval_source_manifest_ref = artifact_store.write_json_artifact(
        stage="indexing",
        artifact_type="retrieval-source-manifest",
        payload=state.analysis_bundle.rag_sources.model_dump(mode="json"),
        producer="indexer",
        input_artifact_refs=[ref for ref in [state.analysis_bundle_ref] if ref is not None],
        event_ref=started.event_id,
        attempt=attempt,
    )
    indexing_plan_ref = artifact_store.write_json_artifact(
        stage="indexing",
        artifact_type="indexing-plan",
        payload=retrieval_plan.model_dump(mode="json"),
        producer="indexer",
        input_artifact_refs=[ref for ref in [state.plan_ref] if ref is not None],
        event_ref=started.event_id,
        attempt=attempt,
    )
    indexing_result_ref = artifact_store.write_json_artifact(
        stage="indexing",
        artifact_type="indexing-result",
        payload=indexing_result,
        producer="indexer",
        input_artifact_refs=[retrieval_source_manifest_ref, indexing_plan_ref],
        event_ref=started.event_id,
        attempt=attempt,
        status="completed",
    )
    retrieval_smoke_ref = artifact_store.write_json_artifact(
        stage="indexing",
        artifact_type="retrieval-smoke",
        payload=smoke_payload,
        producer="indexer",
        input_artifact_refs=[indexing_result_ref],
        event_ref=started.event_id,
        attempt=attempt,
        status="completed" if smoke_payload.get("passed", False) else "failed",
    )

    state.indexing_result = indexing_result
    state.retrieval_source_manifest_ref = retrieval_source_manifest_ref
    state.indexing_plan_ref = indexing_plan_ref
    state.indexing_result_ref = indexing_result_ref
    state.retrieval_smoke_ref = retrieval_smoke_ref
    state.plan = _apply_indexing_result_to_plan(plan=state.plan, indexing_result=indexing_result)
    _mark_required_stage_rechecks_satisfied(state=state, satisfied=["indexing"])
    event_store.write_event(
        run_id=run_id,
        stage="indexing",
        phase="finish",
        event_type="stage_completed",
        summary="indexing completed",
        artifact_refs=[retrieval_source_manifest_ref, indexing_plan_ref, indexing_result_ref, retrieval_smoke_ref],
        attempt=attempt,
    )


def _build_host_export_context(
    *,
    state: _RunState,
    export_ready: bool = False,
) -> HostExportContext:
    context = HostExportContext(
        host_runtime_workspace=(
            None
            if state.apply_result is None
            else Path(state.apply_result.host_workspace_path)
        ),
        snapshot=state.snapshot,
        integration_plan=state.plan,
    )
    if export_ready and context.host_runtime_workspace is not None:
        context.export_ready.set()
    return context


def _mark_host_export_ready(*, host_context: HostExportContext, state: _RunState) -> None:
    if state.apply_result is not None:
        host_context.host_runtime_workspace = Path(state.apply_result.host_workspace_path)
    host_context.snapshot = state.snapshot
    host_context.integration_plan = state.plan
    host_context.export_ready.set()


def run_compile_preflight_stage(
    *,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    attempt: int,
) -> None:
    try:
        if (
            state.edit_program is None
            or state.compile_ref is None
            or state.chatbot_compile_ref is None
            or state.apply_result is None
            or state.apply_ref is None
        ):
            raise ValueError(
                "compile artifacts and apply result are required before compile preflight"
            )
        preflight_spec = state.edit_program.chatbot_program.compile_preflight
        ran_check = False

        if preflight_spec is not None:
            ran_check = True
            started = event_store.write_event(
                run_id=run_id,
                stage="compile",
                phase="preflight_start",
                event_type="compile_preflight_started",
                summary="chatbot compile preflight started",
                input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                attempt=attempt,
            )
            preflight_result = run_chatbot_compile_preflight(
                Path(state.apply_result.chatbot_workspace_path),
                scan_paths=preflight_spec.scan_paths,
            )
            preflight_payload = {
                "artifact_type": preflight_spec.artifact_type,
                "check_name": preflight_spec.check_name,
                "chatbot_workspace_path": state.apply_result.chatbot_workspace_path,
                "scan_paths": list(preflight_spec.scan_paths),
                **preflight_result.model_dump(mode="json"),
            }
            preflight_ref = artifact_store.write_json_artifact(
                stage="compile",
                artifact_type=preflight_spec.artifact_type,
                payload=preflight_payload,
                producer="compiler",
                input_artifact_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                event_ref=started.event_id,
                status="completed" if preflight_result.passed else "failed",
                attempt=attempt,
            )
            state.compile_preflight_ref = preflight_ref
            state.compile_preflight_result = preflight_result

            if not preflight_result.passed:
                failure_summary = preflight_result.failure_summary or "chatbot compile preflight failed"
                failure_signature = build_failure_signature(
                    check_name=preflight_spec.check_name,
                    summary=f"{preflight_result.failure_code or 'compile_preflight_failed'}: {failure_summary}",
                )
                failed_event = event_store.write_event(
                    run_id=run_id,
                    stage="compile",
                    phase="preflight_finish",
                    event_type="stage_failed",
                    summary="chatbot compile preflight failed",
                    artifact_refs=[preflight_ref],
                    input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                    failure_signature=failure_signature,
                    attempt=attempt,
                )
                raise _StageFailure(
                    stage="compile",
                    failure_signature=failure_signature,
                    failure_summary=failure_summary,
                    trigger_event_id=failed_event.event_id,
                    related_artifacts=[
                        state.compile_ref,
                        state.chatbot_compile_ref,
                        state.apply_ref,
                        preflight_ref,
                    ],
                    related_files=preflight_result.related_files,
                    input_artifact_versions=_artifact_versions(state),
                    workspace_root=state.apply_result.chatbot_workspace_path,
                    payload=preflight_payload,
                )

            event_store.write_event(
                run_id=run_id,
                stage="compile",
                phase="preflight_finish",
                event_type="compile_preflight_completed",
                summary="chatbot compile preflight completed",
                artifact_refs=[preflight_ref],
                input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                attempt=attempt,
            )

        if (
            state.snapshot is not None
            and state.snapshot.repo_profile.backend_framework == "flask"
            and state.apply_result.host_workspace_path
        ):
            ran_check = True
            host_workspace = Path(state.apply_result.host_workspace_path)
            backend_root = host_workspace / "backend" if (host_workspace / "backend").exists() else host_workspace
            entrypoint = _choose_backend_entrypoint(
                snapshot=state.snapshot,
                backend_root=backend_root,
                defaults=("app.py", "run.py"),
            )
            host_started = event_store.write_event(
                run_id=run_id,
                stage="compile",
                phase="host_import_smoke_start",
                event_type="host_import_smoke_started",
                summary="host import smoke started",
                input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                attempt=attempt,
            )
            host_result = run_flask_host_import_smoke(
                host_workspace=host_workspace,
                entrypoint=entrypoint,
            )
            host_payload = {
                "artifact_type": "host-import-smoke",
                "check_name": "host_backend_import",
                "host_workspace_path": state.apply_result.host_workspace_path,
                "entrypoint": entrypoint,
                **host_result.model_dump(mode="json"),
            }
            host_ref = artifact_store.write_json_artifact(
                stage="compile",
                artifact_type="host-import-smoke",
                payload=host_payload,
                producer="compiler",
                input_artifact_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                event_ref=host_started.event_id,
                status="completed" if host_result.passed else "failed",
                attempt=attempt,
            )
            state.host_import_smoke_ref = host_ref
            state.host_import_smoke_result = host_result

            if not host_result.passed:
                failure_summary = host_result.failure_summary or "host import smoke failed"
                failure_signature = build_failure_signature(
                    check_name="host_backend_import",
                    summary=f"{host_result.failure_code or 'host_import_smoke_failed'}: {failure_summary}",
                )
                failed_event = event_store.write_event(
                    run_id=run_id,
                    stage="compile",
                    phase="host_import_smoke_finish",
                    event_type="stage_failed",
                    summary="host import smoke failed",
                    artifact_refs=[host_ref],
                    input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                    failure_signature=failure_signature,
                    attempt=attempt,
                )
                raise _StageFailure(
                    stage="compile",
                    failure_signature=failure_signature,
                    failure_summary=failure_summary,
                    trigger_event_id=failed_event.event_id,
                    related_artifacts=[
                        ref
                        for ref in [
                            state.compile_ref,
                            state.chatbot_compile_ref,
                            state.apply_ref,
                            state.compile_preflight_ref,
                            host_ref,
                        ]
                        if ref is not None
                    ],
                    related_files=host_result.related_files,
                    input_artifact_versions=_artifact_versions(state),
                    workspace_root=state.apply_result.host_workspace_path,
                    payload=host_payload,
                )

            event_store.write_event(
                run_id=run_id,
                stage="compile",
                phase="host_import_smoke_finish",
                event_type="host_import_smoke_completed",
                summary="host import smoke completed",
                artifact_refs=[host_ref],
                input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref],
                attempt=attempt,
            )

        if ran_check:
            _mark_required_rechecks_satisfied(state=state, satisfied=["compile_preflight"])
        return
    except _StageFailure:
        raise
    except Exception as exc:
        failure_summary = (
            f"unexpected compile preflight error: {exc.__class__.__name__}: {exc}"
        )
        failure_signature = build_failure_signature(
            check_name="chatbot_runtime_import",
            summary=failure_summary,
        )
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="compile",
            phase="preflight_finish",
            event_type="stage_failed",
            summary="chatbot compile preflight crashed",
            details={"error": str(exc), "error_type": exc.__class__.__name__},
            input_refs=[state.compile_ref, state.chatbot_compile_ref, state.apply_ref]
            if state.compile_ref is not None
            and state.chatbot_compile_ref is not None
            and state.apply_ref is not None
            else [],
            failure_signature=failure_signature,
            attempt=attempt,
        )
        raise _StageFailure(
            stage="compile",
            failure_signature=failure_signature,
            failure_summary=failure_summary,
            trigger_event_id=failed_event.event_id,
            related_artifacts=[
                ref
                for ref in [
                    state.compile_ref,
                    state.chatbot_compile_ref,
                    state.apply_ref,
                    state.compile_preflight_ref,
                    state.host_import_smoke_ref,
                ]
                if ref is not None
            ],
            related_files=[],
            input_artifact_versions=_artifact_versions(state),
            workspace_root=state.apply_result.chatbot_workspace_path
            if state.apply_result is not None
            else None,
            payload={"error": str(exc), "error_type": exc.__class__.__name__},
        )


def run_validation_stage(
    *,
    run_root: Path,
    run_id: str,
    state: _RunState,
    event_store: EventStore,
    artifact_store: ArtifactStore,
    onboarding_credentials: dict[str, str] | None,
    attempt: int,
) -> None:
    if (
        state.snapshot is None
        or state.analysis_ref is None
        or state.plan is None
        or state.plan_ref is None
        or state.compile_ref is None
        or state.chatbot_compile_ref is None
        or state.apply_result is None
        or state.apply_ref is None
        or state.replay_result is None
        or state.replay_ref is None
    ):
        raise ValueError(
            "analysis, plan, compile, apply, and replay results are required before validation"
        )

    validation_started = event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="start",
        event_type="stage_started",
        summary="validation started",
        input_refs=[
            state.analysis_ref,
            state.plan_ref,
            state.compile_ref,
            state.chatbot_compile_ref,
            state.apply_ref,
            state.replay_ref,
            *(
                []
                if state.indexing_result_ref is None
                else [state.indexing_result_ref]
            ),
        ],
        attempt=attempt,
    )
    validation_live_logs_root = run_root / "artifacts" / "05-validation" / "live-logs"
    validation_live_logs_root.mkdir(parents=True, exist_ok=True)

    def _validation_event_callback(payload: dict[str, object]) -> None:
        event_store.write_event(
            run_id=run_id,
            stage="validation",
            attempt=attempt,
            **payload,
        )

    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="prep_start",
        event_type="backend_runtime_prep_started",
        summary="backend runtime prep started",
        input_refs=[state.analysis_ref, state.plan_ref, state.apply_ref],
        attempt=attempt,
    )
    validation_run = run_validation_cycle(
        run_root=run_root,
        host_runtime_workspace=state.apply_result.host_workspace_path,
        chatbot_runtime_workspace=state.apply_result.chatbot_workspace_path,
        snapshot=state.snapshot,
        plan=state.plan,
        replay_result=state.replay_result,
        artifact_refs={
            "analysis": state.analysis_ref,
            "planning": state.plan_ref,
            "compile": state.compile_ref,
            "compile_chatbot": state.chatbot_compile_ref,
            "apply": state.apply_ref,
            "replay": state.replay_ref,
            "indexing": state.indexing_result_ref,
        },
        onboarding_credentials=onboarding_credentials,
        required_rechecks=list(state.pending_required_rechecks),
        event_callback=_validation_event_callback,
        live_logs_root=validation_live_logs_root,
        retrieval_status=state.indexing_result,
    )
    prep_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="backend-runtime-prep",
        payload=validation_run.backend_runtime_prep.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[state.analysis_ref, state.plan_ref, state.apply_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.backend_runtime_prep.passed else "failed",
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="prep_finish",
        event_type="backend_runtime_prep_completed",
        summary=(
            "backend runtime prep completed"
            if validation_run.backend_runtime_prep.passed
            else "backend runtime prep failed"
        ),
        artifact_refs=[prep_ref],
        input_refs=[state.analysis_ref, state.plan_ref, state.apply_ref],
        failure_signature=(
            None
            if validation_run.backend_runtime_prep.passed
            else build_failure_signature(
                check_name="backend_runtime_prep",
                summary=validation_run.backend_runtime_prep.failure_summary
                or "backend runtime prep failed",
            )
        ),
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="boot_start",
        event_type="backend_runtime_boot_started",
        summary="backend runtime boot started",
        input_refs=[prep_ref],
        attempt=attempt,
    )
    state_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="backend-runtime-state",
        payload=validation_run.backend_runtime_state.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[prep_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.backend_runtime_state.passed else "failed",
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="boot_finish",
        event_type="backend_runtime_boot_completed",
        summary=(
            "backend runtime boot completed"
            if validation_run.backend_runtime_state.passed
            else "backend runtime boot failed"
        ),
        artifact_refs=[state_ref],
        input_refs=[prep_ref],
        failure_signature=(
            None if validation_run.backend_runtime_state.passed else "backend_runtime_boot_failed"
        ),
        attempt=attempt,
    )
    chatbot_runtime_boot_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="chatbot-runtime-boot",
        payload=validation_run.chatbot_runtime_boot,
        producer="validator",
        input_artifact_refs=[state_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.chatbot_runtime_boot["passed"] else "failed",
        attempt=attempt,
    )
    widget_bundle_fetch_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="widget-bundle-fetch",
        payload=validation_run.widget_bundle_fetch,
        producer="validator",
        input_artifact_refs=[state_ref, chatbot_runtime_boot_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.widget_bundle_fetch["passed"] else "failed",
        attempt=attempt,
    )
    host_auth_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="host-auth-bootstrap",
        payload=validation_run.host_auth_bootstrap,
        producer="validator",
        input_artifact_refs=[state_ref, chatbot_runtime_boot_ref, widget_bundle_fetch_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.host_auth_bootstrap["passed"] else "failed",
        attempt=attempt,
    )
    chatbot_adapter_auth_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="chatbot-adapter-auth",
        payload=validation_run.chatbot_adapter_auth,
        producer="validator",
        input_artifact_refs=[host_auth_ref, state_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.chatbot_adapter_auth["passed"] else "failed",
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="widget_start",
        event_type="widget_e2e_started",
        summary="widget order e2e started",
        input_refs=[host_auth_ref, chatbot_adapter_auth_ref],
        attempt=attempt,
    )
    widget_order_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="widget-order-e2e",
        payload=validation_run.widget_order_e2e.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[host_auth_ref, chatbot_adapter_auth_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.widget_order_e2e.passed else "failed",
        attempt=attempt,
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="widget_finish",
        event_type="widget_e2e_completed",
        summary=(
            "widget order e2e completed"
            if validation_run.widget_order_e2e.passed
            else "widget order e2e failed"
        ),
        artifact_refs=[widget_order_ref],
        input_refs=[host_auth_ref, chatbot_adapter_auth_ref],
        failure_signature=(
            None if validation_run.widget_order_e2e.passed else "widget_order_e2e_failed"
        ),
        attempt=attempt,
    )
    fixture_manifest_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="validation-fixture-manifest",
        payload=dict(validation_run.conversation_validation.fixture_manifest or {}),
        producer="validator",
        input_artifact_refs=[prep_ref, host_auth_ref, chatbot_adapter_auth_ref],
        event_ref=validation_started.event_id,
        status="completed",
        attempt=attempt,
    )
    conversation_transcript_refs: list[ArtifactRef] = []
    for scenario_id, content in sorted(
        validation_run.conversation_validation.transcript_contents.items()
    ):
        transcript_ref = artifact_store.write_text_artifact(
            stage="validation",
            artifact_type="conversation-transcript",
            content=content,
            suffix=f"-{scenario_id}.json",
        )
        conversation_transcript_refs.append(transcript_ref)
    conversation_validation_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="conversation-validation",
        payload=validation_run.conversation_validation.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[
            state_ref,
            chatbot_runtime_boot_ref,
            widget_bundle_fetch_ref,
            host_auth_ref,
            chatbot_adapter_auth_ref,
            widget_order_ref,
            fixture_manifest_ref,
            *conversation_transcript_refs,
        ],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.conversation_validation.passed else "failed",
        attempt=attempt,
    )
    validation_bundle = validation_run.bundle
    validation_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="validation-bundle",
        payload=validation_bundle.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[
            state.analysis_ref,
            state.plan_ref,
            state.compile_ref,
            state.chatbot_compile_ref,
            state.apply_ref,
            state.replay_ref,
            *([state.indexing_result_ref] if state.indexing_result_ref is not None else []),
            prep_ref,
            state_ref,
            chatbot_runtime_boot_ref,
            widget_bundle_fetch_ref,
            host_auth_ref,
            chatbot_adapter_auth_ref,
            widget_order_ref,
            fixture_manifest_ref,
            conversation_validation_ref,
            *conversation_transcript_refs,
        ],
        event_ref=validation_started.event_id,
        status="completed" if validation_bundle.passed else "failed",
        attempt=attempt,
    )
    _mark_required_stage_rechecks_satisfied(state=state, satisfied=["validation"])
    if not validation_bundle.passed:
        failed_event = event_store.write_event(
            run_id=run_id,
            stage="validation",
            phase="finish",
            event_type="stage_failed",
            summary="validation failed",
            artifact_refs=[validation_ref],
            input_refs=[
                state.analysis_ref,
                state.plan_ref,
                state.compile_ref,
                state.chatbot_compile_ref,
                state.apply_ref,
                state.replay_ref,
                *([state.indexing_result_ref] if state.indexing_result_ref is not None else []),
            ],
            failure_signature=validation_bundle.failure_signature,
            attempt=attempt,
        )
        state.validation_run = validation_run
        state.prep_ref = prep_ref
        state.state_ref = state_ref
        state.chatbot_runtime_boot_ref = chatbot_runtime_boot_ref
        state.widget_bundle_fetch_ref = widget_bundle_fetch_ref
        state.host_auth_ref = host_auth_ref
        state.chatbot_adapter_auth_ref = chatbot_adapter_auth_ref
        state.widget_order_ref = widget_order_ref
        state.fixture_manifest_ref = fixture_manifest_ref
        state.conversation_validation_ref = conversation_validation_ref
        state.conversation_transcript_refs = conversation_transcript_refs
        state.validation_ref = validation_ref
        raise _StageFailure(
            stage="validation",
            failure_signature=validation_bundle.failure_signature
            or build_failure_signature(
                check_name="validation",
                summary=validation_bundle.failure_summary or "validation failed",
            ),
            failure_summary=validation_bundle.failure_summary or "validation failed",
            trigger_event_id=failed_event.event_id,
            related_artifacts=[
                state.analysis_ref,
                state.plan_ref,
                state.compile_ref,
                state.chatbot_compile_ref,
                state.apply_ref,
                state.replay_ref,
                *([state.indexing_result_ref] if state.indexing_result_ref is not None else []),
                prep_ref,
                state_ref,
                widget_bundle_fetch_ref,
                host_auth_ref,
                chatbot_adapter_auth_ref,
                widget_order_ref,
                fixture_manifest_ref,
                conversation_validation_ref,
                *conversation_transcript_refs,
                validation_ref,
            ],
            related_files=validation_bundle.related_files,
            input_artifact_versions=_artifact_versions(state),
            workspace_root=state.apply_result.workspace_path,
            payload=validation_bundle.model_dump(mode="json"),
        )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="finish",
        event_type="stage_completed",
        summary="validation completed",
        artifact_refs=[validation_ref],
        input_refs=[
            state.analysis_ref,
            state.plan_ref,
            state.compile_ref,
            state.chatbot_compile_ref,
            state.apply_ref,
            state.replay_ref,
            *([state.indexing_result_ref] if state.indexing_result_ref is not None else []),
        ],
        attempt=attempt,
    )
    state.validation_run = validation_run
    state.prep_ref = prep_ref
    state.state_ref = state_ref
    state.chatbot_runtime_boot_ref = chatbot_runtime_boot_ref
    state.widget_bundle_fetch_ref = widget_bundle_fetch_ref
    state.host_auth_ref = host_auth_ref
    state.chatbot_adapter_auth_ref = chatbot_adapter_auth_ref
    state.widget_order_ref = widget_order_ref
    state.fixture_manifest_ref = fixture_manifest_ref
    state.conversation_validation_ref = conversation_validation_ref
    state.conversation_transcript_refs = conversation_transcript_refs
    state.validation_ref = validation_ref
    state.latest_failure_signature = None
    _mark_required_rechecks_satisfied(
        state=state,
        satisfied=[check.name for check in validation_bundle.checks],
    )
    if not state.pending_required_rechecks and not state.pending_required_stage_rechecks:
        state.pending_preserve_artifacts = []


def _related_compile_files(plan: IntegrationPlan) -> list[str]:
    return [
        plan.host_backend.route_target,
        plan.host_backend.import_target,
        plan.host_frontend.mount_target,
        plan.host_frontend.api_client_target,
        plan.chatbot_bridge.setup_target,
        f"{plan.chatbot_bridge.adapter_package}/adapter.py",
    ]


def _artifact_versions(state: _RunState) -> dict[str, int]:
    mapping = {
        "analysis": state.analysis_ref,
        "planning": state.plan_ref,
        "compile": state.compile_ref,
        "compile_chatbot": state.chatbot_compile_ref,
        "compile_preflight": state.compile_preflight_ref,
        "host_import_smoke": state.host_import_smoke_ref,
        "apply": state.apply_ref,
        "export": state.export_bundle_ref,
        "indexing": state.indexing_result_ref,
        "validation": state.validation_ref,
    }
    return {stage: ref.version for stage, ref in mapping.items() if ref is not None}


def _successful_retrieval_corpora(indexing_result: dict[str, Any] | None) -> list[str]:
    corpora = dict((indexing_result or {}).get("corpora") or {})
    successful: list[str] = []
    for corpus, payload in corpora.items():
        details = dict(payload or {})
        if str(details.get("status") or "") == "completed" and bool(details.get("enabled", True)):
            if bool(details.get("smoke_passed", True)):
                successful.append(str(corpus))
    return successful


def _apply_indexing_result_to_plan(
    *,
    plan: IntegrationPlan,
    indexing_result: dict[str, Any] | None,
) -> IntegrationPlan:
    enabled_corpora = _successful_retrieval_corpora(indexing_result)
    capability_profile = "order_cs_plus_retrieval" if enabled_corpora else "order_cs_only"
    widget_features = {"image_upload": "discovery_image" in enabled_corpora}
    return plan.model_copy(
        update={
            "host_backend": plan.host_backend.model_copy(
                update={
                    "capability_profile": capability_profile,
                    "enabled_retrieval_corpora": enabled_corpora,
                    "widget_features": widget_features,
                }
            ),
            "host_frontend": plan.host_frontend.model_copy(
                update={
                    "capability_profile": capability_profile,
                    "enabled_retrieval_corpora": enabled_corpora,
                    "widget_features": widget_features,
                }
            ),
            "capability_upgrade": {
                "capability_profile": capability_profile,
                "enabled_retrieval_corpora": enabled_corpora,
                "widget_features": widget_features,
            },
        }
    )


def _build_retrieval_smoke_payload(
    *,
    retrieval_plan: Any,
    indexing_result: dict[str, Any],
) -> dict[str, Any]:
    status_map = dict(indexing_result.get("corpora") or {})
    results: list[dict[str, Any]] = []
    passed = True
    for corpus_plan in retrieval_plan.corpora:
        payload = dict(status_map.get(corpus_plan.corpus) or {})
        raw_status = str(payload.get("status") or "").strip()
        corpus_status = "failed"
        if raw_status == "skipped":
            corpus_status = "skipped"
        elif (
            raw_status == "completed"
            and int(payload.get("documents_indexed") or 0) >= int(corpus_plan.minimum_expected_documents)
        ):
            corpus_status = "passed"
        corpus_passed = corpus_status != "failed"
        if not corpus_passed:
            passed = False
        results.append(
            {
                "corpus": corpus_plan.corpus,
                "passed": corpus_passed,
                "status": corpus_status,
                "summary": (
                    f"{corpus_plan.corpus} retrieval smoke passed"
                    if corpus_status == "passed"
                    else (
                        f"{corpus_plan.corpus} retrieval smoke skipped"
                        if corpus_status == "skipped"
                        else f"{corpus_plan.corpus} retrieval smoke failed"
                    )
                ),
                "details": payload,
            }
        )
    return {"passed": passed, "results": results}


def _write_llm_usage_summary_artifact(
    *,
    artifact_store: ArtifactStore,
    usage_store: LlmUsageStore,
    analysis_ref: ArtifactRef | None,
    plan_ref: ArtifactRef | None,
    attempt: int,
) -> ArtifactRef | None:
    summary_payload = usage_store.read_summary()
    if not summary_payload or not list(summary_payload.get("calls") or []):
        return None
    return artifact_store.write_json_artifact(
        stage="export",
        artifact_type="llm-usage-summary",
        payload=summary_payload,
        producer="llm_usage_store",
        input_artifact_refs=[ref for ref in (analysis_ref, plan_ref) if ref is not None],
        attempt=attempt,
    )


def _artifact_abspath(run_root: Path, artifact_ref: ArtifactRef | None) -> str | None:
    if artifact_ref is None:
        return None
    stage_dir = STAGE_DIRECTORY_MAP[artifact_ref.stage]
    return str(run_root / "artifacts" / stage_dir / artifact_ref.artifact_type / artifact_ref.path)


def _failure_validation_payload(state: _RunState) -> dict[str, Any]:
    if state.validation_run is None:
        return {}
    return state.validation_run.bundle.model_dump(mode="json")


def _resolve_workspace_root(*, source_root: str, state: _RunState) -> str:
    if state.apply_result is not None:
        return state.apply_result.workspace_path
    return source_root


def _derive_effective_rewind_to(decision: RepairDecision) -> str:
    artifact_overrides = dict(decision.artifact_overrides or {})
    if dict(artifact_overrides.get("analysis") or {}):
        return "analysis"
    if dict(artifact_overrides.get("planning") or {}):
        return "planning"
    if dict(artifact_overrides.get("compile") or {}):
        return "compile"
    return decision.rewind_to


_STAGE_RECHECK_NAMES = ("analysis", "planning", "compile", "apply", "export", "indexing", "validation")
_CHECK_RECHECK_NAMES = (
    "compile_preflight",
    "backend_runtime_prep",
    "backend_runtime_boot",
    "chatbot_runtime_boot",
    "widget_bundle_fetch",
    "host_auth_bootstrap",
    "chatbot_adapter_auth",
    "widget_order_e2e",
    "retrieval_faq",
    "retrieval_policy",
    "retrieval_discovery_image",
    "replay_apply",
    "replay_validation",
)


def _normalize_required_rechecks(required_rechecks: list[str]) -> dict[str, list[str]]:
    stage_rechecks: list[str] = []
    check_rechecks: list[str] = []
    ignored_rechecks: list[str] = []
    seen_stage: set[str] = set()
    seen_check: set[str] = set()
    seen_ignored: set[str] = set()

    for item in required_rechecks:
        token = str(item or "").strip()
        if not token:
            continue
        if token in _STAGE_RECHECK_NAMES:
            if token not in seen_stage:
                seen_stage.add(token)
                stage_rechecks.append(token)
            continue
        if token in _CHECK_RECHECK_NAMES:
            if token not in seen_check:
                seen_check.add(token)
                check_rechecks.append(token)
            continue
        if token not in seen_ignored:
            seen_ignored.add(token)
            ignored_rechecks.append(token)

    return {
        "stage_rechecks": stage_rechecks,
        "check_rechecks": check_rechecks,
        "ignored_rechecks": ignored_rechecks,
    }


def _combined_pending_required_rechecks(state: _RunState) -> list[str]:
    return list(
        dict.fromkeys(
            [*state.pending_required_stage_rechecks, *state.pending_required_rechecks]
        )
    )


def _clear_state_for_failure(
    *,
    state: _RunState,
    failed_stage: str,
    rewind_to: str,
    preserve_artifacts: list[str],
) -> None:
    del failed_stage
    rerun_stages = set(_stages_from(rewind_to))
    transiently_preserved = (
        {"indexing"} if _should_transiently_preserve_indexing(state=state, rewind_to=rewind_to) else set()
    )
    preserved = {
        stage for stage in preserve_artifacts if stage in _stage_order() and stage not in rerun_stages
    }
    for stage in _stage_order():
        if stage in transiently_preserved:
            continue
        if stage in rerun_stages or stage not in preserved:
            _clear_from_stage_exact(state, stage)


def _clear_from_stage(state: _RunState, stage: str) -> None:
    if stage == "analysis":
        state.snapshot = None
        state.analysis_ref = None
        _clear_from_stage(state, "planning")
        return
    if stage == "planning":
        state.plan = None
        state.plan_ref = None
        _clear_from_stage(state, "compile")
        return
    if stage == "compile":
        state.edit_program = None
        state.compile_ref = None
        state.chatbot_compile_ref = None
        state.compile_preflight_ref = None
        state.compile_preflight_result = None
        state.host_import_smoke_ref = None
        state.host_import_smoke_result = None
        _clear_from_stage(state, "apply")
        return
    if stage == "apply":
        state.apply_result = None
        state.apply_ref = None
        state.compile_preflight_ref = None
        state.compile_preflight_result = None
        state.host_import_smoke_ref = None
        state.host_import_smoke_result = None
        _clear_from_stage(state, "export")
        return
    if stage == "export":
        state.patch_ref = None
        state.chatbot_patch_ref = None
        state.replay_result = None
        state.replay_ref = None
        state.export_bundle_ref = None
        _clear_from_stage(state, "indexing")
        return
    if stage == "indexing":
        state.retrieval_source_manifest_ref = None
        state.indexing_plan_ref = None
        state.indexing_result_ref = None
        state.retrieval_smoke_ref = None
        state.indexing_result = None
        _clear_from_stage(state, "validation")
        return
    if stage == "validation":
        state.validation_run = None
        state.prep_ref = None
        state.state_ref = None
        state.chatbot_runtime_boot_ref = None
        state.widget_bundle_fetch_ref = None
        state.host_auth_ref = None
        state.chatbot_adapter_auth_ref = None
        state.widget_order_ref = None
        state.fixture_manifest_ref = None
        state.conversation_validation_ref = None
        state.conversation_transcript_refs = []
        state.validation_ref = None


def _clear_from_stage_exact(state: _RunState, stage: str) -> None:
    if stage == "analysis":
        state.analysis_bundle = None
        state.snapshot = None
        state.analysis_bundle_ref = None
        state.analysis_ref = None
        return
    if stage == "planning":
        state.planning_bundle = None
        state.plan = None
        state.planning_bundle_ref = None
        state.plan_ref = None
        return
    if stage == "compile":
        state.edit_program = None
        state.compile_ref = None
        state.chatbot_compile_ref = None
        state.compile_preflight_ref = None
        state.compile_preflight_result = None
        state.host_import_smoke_ref = None
        state.host_import_smoke_result = None
        return
    if stage == "apply":
        state.apply_result = None
        state.apply_ref = None
        state.compile_preflight_ref = None
        state.compile_preflight_result = None
        state.host_import_smoke_ref = None
        state.host_import_smoke_result = None
        return
    if stage == "export":
        state.patch_ref = None
        state.chatbot_patch_ref = None
        state.replay_result = None
        state.replay_ref = None
        state.export_bundle_ref = None
        return
    if stage == "indexing":
        state.retrieval_source_manifest_ref = None
        state.indexing_plan_ref = None
        state.indexing_result_ref = None
        state.retrieval_smoke_ref = None
        state.indexing_result = None
        return
    if stage == "validation":
        state.validation_run = None
        state.prep_ref = None
        state.state_ref = None
        state.chatbot_runtime_boot_ref = None
        state.widget_bundle_fetch_ref = None
        state.host_auth_ref = None
        state.chatbot_adapter_auth_ref = None
        state.widget_order_ref = None
        state.fixture_manifest_ref = None
        state.conversation_validation_ref = None
        state.conversation_transcript_refs = []
        state.validation_ref = None
        return


def _stage_order() -> list[str]:
    return ["analysis", "planning", "compile", "apply", "export", "indexing", "validation"]


def _stages_from(stage: str) -> list[str]:
    ordered = _stage_order()
    try:
        start = ordered.index(stage)
    except ValueError:
        return []
    return ordered[start:]


def _mark_required_rechecks_satisfied(*, state: _RunState, satisfied: list[str]) -> None:
    if not state.pending_required_rechecks:
        return
    satisfied_set = {item for item in satisfied if item}
    if not satisfied_set:
        return
    state.pending_required_rechecks = [
        item for item in state.pending_required_rechecks if item not in satisfied_set
    ]


def _mark_required_stage_rechecks_satisfied(*, state: _RunState, satisfied: list[str]) -> None:
    if not state.pending_required_stage_rechecks:
        return
    satisfied_set = {item for item in satisfied if item}
    if not satisfied_set:
        return
    state.pending_required_stage_rechecks = [
        item for item in state.pending_required_stage_rechecks if item not in satisfied_set
    ]


def _apply_analysis_overrides(
    *,
    snapshot: AnalysisSnapshot,
    overrides: dict[str, Any],
) -> AnalysisSnapshot:
    if not overrides:
        return snapshot
    confidence_notes = list(snapshot.provenance.confidence_notes)
    note = str(overrides.get("notes") or "").strip()
    if note:
        confidence_notes.append(note)
    return snapshot.model_copy(
        update={
            "provenance": snapshot.provenance.model_copy(
                update={"confidence_notes": confidence_notes}
            )
        }
    )


def _apply_planning_overrides(
    *,
    plan: IntegrationPlan,
    overrides: dict[str, Any],
) -> IntegrationPlan:
    if not overrides:
        return plan
    backend_override = dict(overrides.get("backend_wiring") or overrides.get("host_backend") or {})
    frontend_override = dict(
        overrides.get("frontend_integration") or overrides.get("host_frontend") or {}
    )
    chatbot_override = dict(overrides.get("chatbot_bridge") or {})
    chatbot_response_contract_override = dict(chatbot_override.pop("response_contract", {}) or {})
    notes_append = str(overrides.get("planning_notes_append") or "").strip()
    rationale = list(plan.planning_notes.llm_rationale)
    if notes_append:
        rationale.append(notes_append)
    chatbot_bridge = plan.chatbot_bridge.model_copy(update=chatbot_override)
    if chatbot_response_contract_override:
        chatbot_bridge = chatbot_bridge.model_copy(
            update={
                "response_contract": chatbot_bridge.response_contract.model_copy(
                    update=chatbot_response_contract_override
                )
            }
        )
    return plan.model_copy(
        update={
            "host_backend": plan.host_backend.model_copy(update=backend_override),
            "host_frontend": plan.host_frontend.model_copy(update=frontend_override),
            "chatbot_bridge": chatbot_bridge,
            "planning_notes": plan.planning_notes.model_copy(
                update={"llm_rationale": rationale}
            ),
        }
    )


def _retrieval_plan_signature(retrieval_plan: Any) -> dict[str, Any] | None:
    if retrieval_plan is None:
        return None
    if hasattr(retrieval_plan, "model_dump"):
        return retrieval_plan.model_dump(mode="json")
    return dict(retrieval_plan)


def _should_transiently_preserve_indexing(
    *,
    state: _RunState,
    rewind_to: str,
) -> bool:
    return rewind_to == "planning" and state.indexing_result is not None


def _reconcile_preserved_indexing_after_planning(
    *,
    state: _RunState,
    previous_retrieval_plan: Any,
) -> None:
    if state.plan is None or state.indexing_result is None:
        return
    if _retrieval_plan_signature(previous_retrieval_plan) != _retrieval_plan_signature(
        state.plan.retrieval_index_plan
    ):
        _clear_from_stage_exact(state, "indexing")
        return
    state.plan = _apply_indexing_result_to_plan(
        plan=state.plan,
        indexing_result=state.indexing_result,
    )
