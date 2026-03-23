from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.compile.preflight import (
    CompilePreflightResult,
    run_chatbot_compile_preflight,
)
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.models import (
    AnalysisSnapshot,
    ApplyResult,
    ArtifactRef,
    EditProgram,
    IntegrationPlan,
    ReplayResult,
)
from chatbot.src.onboarding_v2.models.validation import ValidationBundle
from chatbot.src.onboarding_v2.planning import build_integration_plan
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
    RunStore,
    ViewProjector,
)
from chatbot.src.onboarding_v2.validation.runner import (
    ValidationRunResult,
    run_validation_cycle,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


@dataclass(slots=True)
class _RunState:
    snapshot: AnalysisSnapshot | None = None
    analysis_ref: ArtifactRef | None = None
    plan: IntegrationPlan | None = None
    plan_ref: ArtifactRef | None = None
    edit_program: EditProgram | None = None
    compile_ref: ArtifactRef | None = None
    chatbot_compile_ref: ArtifactRef | None = None
    compile_preflight_ref: ArtifactRef | None = None
    compile_preflight_result: CompilePreflightResult | None = None
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
    host_auth_ref: ArtifactRef | None = None
    chatbot_adapter_auth_ref: ArtifactRef | None = None
    widget_order_ref: ArtifactRef | None = None
    validation_ref: ArtifactRef | None = None
    latest_repair_ref: ArtifactRef | None = None
    latest_failure_signature: str | None = None
    latest_rewind_to: str | None = None
    repair_attempt_count: int = 0


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
    chatbot_server_base_url: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    run_root = Path(generated_root) / site / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    event_store = EventStore(run_root)
    artifact_store = ArtifactStore(run_root)
    debug_store = DebugStore(run_root)
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
            decision = diagnose_failure(
                failure_bundle=failure_bundle,
                snapshot_payload=(
                    {} if state.snapshot is None else state.snapshot.model_dump(mode="json")
                ),
                plan_payload={} if state.plan is None else state.plan.model_dump(mode="json"),
                edit_program_payload=(
                    {} if state.edit_program is None else state.edit_program.model_dump(mode="json")
                ),
                validation_payload=_failure_validation_payload(state),
                llm_provider=llm_provider,
                llm_model=llm_model,
                debug_store=debug_store,
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
                    extra_samples = collect_file_samples(
                        workspace_root=_resolve_workspace_root(source_root=source_root, state=state),
                        related_files=discovery_paths,
                    )
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
                        snapshot_payload=(
                            {} if state.snapshot is None else state.snapshot.model_dump(mode="json")
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
                    )

            if repeat_count >= 4:
                decision = decision.model_copy(
                    update={"stop": True, "stop_reason": "repeated_failure_signature"}
                )

            decision_event = event_store.write_event(
                run_id=run_id,
                stage="repair",
                phase="decision",
                event_type="repair_decision_emitted",
                summary="repair decision emitted",
                input_refs=[failure_ref],
                failure_signature=decision.failure_signature,
                rewind_to=decision.rewind_to,
                attempt=attempt,
                actor="repair_agent",
                source="llm",
            )
            decision_ref = artifact_store.write_json_artifact(
                stage="repair",
                artifact_type="repair-decision",
                payload=decision.model_dump(mode="json"),
                producer="repair",
                input_artifact_refs=[failure_ref],
                event_ref=decision_event.event_id,
                status="completed" if not decision.stop else "failed",
                attempt=attempt,
            )
            state.latest_repair_ref = decision_ref
            state.latest_rewind_to = decision.rewind_to
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
                    rewind_to=decision.rewind_to,
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
                summary=f"rewind requested to {decision.rewind_to}",
                input_refs=[failure_ref, decision_ref],
                failure_signature=decision.failure_signature,
                rewind_to=decision.rewind_to,
                attempt=attempt,
                actor="repair_agent",
                source="llm",
            )
            _clear_state_for_failure(
                state=state,
                failed_stage=failure.stage,
                rewind_to=decision.rewind_to,
            )
            analysis_overrides = dict(decision.artifact_overrides.get("analysis") or {})
            planning_overrides = dict(decision.artifact_overrides.get("planning") or {})
            next_stage = decision.rewind_to
            event_store.write_event(
                run_id=run_id,
                stage=next_stage,
                phase="rerun",
                event_type="stage_rerun_started",
                summary=f"{next_stage} rerun started",
                failure_signature=decision.failure_signature,
                rewind_to=decision.rewind_to,
                attempt=attempt + 1,
                actor="repair_agent",
                source="deterministic",
            )

    view_projector.project(
        run_id=run_id,
        site=site,
        status=final_status,
        latest_failure_signature=state.latest_failure_signature,
        latest_rewind_to=state.latest_rewind_to,
        repair_attempt_count=state.repair_attempt_count,
        stopped_for_review=final_status == "failed_human_review",
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
        "latest_plan_artifact": _artifact_abspath(run_root, state.plan_ref),
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
        "latest_apply_artifact": _artifact_abspath(run_root, state.apply_ref),
        "latest_validation_artifact": _artifact_abspath(run_root, state.validation_ref),
        "latest_export_artifact": _artifact_abspath(run_root, state.export_bundle_ref),
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
) -> None:
    stage_order = ["analysis", "planning", "compile", "apply", "export", "validation"]
    start_index = stage_order.index(start_stage)
    for stage in stage_order[start_index:]:
        if stage == "analysis":
            run_analysis_stage(
                site=site,
                source_root=source_root,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
                overrides=analysis_overrides,
            )
            analysis_overrides.clear()
        elif stage == "planning":
            run_planning_stage(
                run_id=run_id,
                chatbot_server_base_url=chatbot_server_base_url,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
                overrides=planning_overrides,
            )
            planning_overrides.clear()
        elif stage == "compile":
            run_compile_stage(
                source_root=source_root,
                chatbot_source_root=chatbot_source_root,
                run_id=run_id,
                state=state,
                event_store=event_store,
                artifact_store=artifact_store,
                attempt=attempt,
            )
        elif stage == "apply":
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
        elif stage == "export":
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
        elif stage == "validation":
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
        snapshot = build_analysis_snapshot(site=site, source_root=source_root)
        snapshot = _apply_analysis_overrides(snapshot=snapshot, overrides=overrides)
        analysis_ref = artifact_store.write_json_artifact(
            stage="analysis",
            artifact_type="snapshot",
            payload=snapshot.model_dump(mode="json"),
            producer="analyzer",
            event_ref=started.event_id,
            attempt=attempt,
        )
        event_store.write_event(
            run_id=run_id,
            stage="analysis",
            phase="finish",
            event_type="stage_completed",
            summary="analysis completed",
            artifact_refs=[analysis_ref],
            attempt=attempt,
        )
        state.snapshot = snapshot
        state.analysis_ref = analysis_ref
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
) -> None:
    if state.snapshot is None or state.analysis_ref is None:
        raise ValueError("analysis snapshot is required before planning")
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
        plan = build_integration_plan(
            state.snapshot,
            chatbot_server_base_url=str(chatbot_server_base_url or ""),
        )
        plan = _apply_planning_overrides(plan=plan, overrides=overrides)
        plan_ref = artifact_store.write_json_artifact(
            stage="planning",
            artifact_type="integration-plan",
            payload=plan.model_dump(mode="json"),
            producer="planner",
            input_artifact_refs=[state.analysis_ref],
            event_ref=started.event_id,
            attempt=attempt,
        )
        event_store.write_event(
            run_id=run_id,
            stage="planning",
            phase="finish",
            event_type="stage_completed",
            summary="planning completed",
            artifact_refs=[plan_ref],
            input_refs=[state.analysis_ref],
            attempt=attempt,
        )
        state.plan = plan
        state.plan_ref = plan_ref
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
        state.snapshot is None
        or state.analysis_ref is None
        or state.plan is None
        or state.plan_ref is None
    ):
        raise ValueError("analysis snapshot and plan are required before compile")
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
            snapshot=state.snapshot,
            plan=state.plan,
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
            failure_signature = build_failure_signature(check_name="apply", summary="apply failed")
            failed_event = event_store.write_event(
                run_id=run_id,
                stage="apply",
                phase="finish",
                event_type="stage_failed",
                summary="apply failed",
                artifact_refs=[apply_ref],
                input_refs=[state.compile_ref, state.chatbot_compile_ref],
                failure_signature=failure_signature,
                attempt=attempt,
            )
            raise _StageFailure(
                stage="apply",
                failure_signature=failure_signature,
                failure_summary="apply failed",
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
            host_runtime_workspace=state.apply_result.host_workspace_path,
            chatbot_runtime_workspace=state.apply_result.chatbot_workspace_path,
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
        if preflight_spec is None:
            return

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
            Path(state.apply_result.chatbot_workspace_path)
        )
        preflight_payload = {
            "artifact_type": preflight_spec.artifact_type,
            "check_name": preflight_spec.check_name,
            "chatbot_workspace_path": state.apply_result.chatbot_workspace_path,
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

        if preflight_result.passed:
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
            return

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
        ],
        attempt=attempt,
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
        },
        onboarding_credentials=onboarding_credentials,
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
            None if validation_run.backend_runtime_prep.passed else "backend_runtime_prep_failed"
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
    host_auth_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="host-auth-bootstrap",
        payload=validation_run.host_auth_bootstrap,
        producer="validator",
        input_artifact_refs=[state_ref, chatbot_runtime_boot_ref],
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
            prep_ref,
            state_ref,
            chatbot_runtime_boot_ref,
            host_auth_ref,
            chatbot_adapter_auth_ref,
            widget_order_ref,
        ],
        event_ref=validation_started.event_id,
        status="completed" if validation_bundle.passed else "failed",
        attempt=attempt,
    )
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
            ],
            failure_signature=validation_bundle.failure_signature,
            attempt=attempt,
        )
        state.validation_run = validation_run
        state.prep_ref = prep_ref
        state.state_ref = state_ref
        state.chatbot_runtime_boot_ref = chatbot_runtime_boot_ref
        state.host_auth_ref = host_auth_ref
        state.chatbot_adapter_auth_ref = chatbot_adapter_auth_ref
        state.widget_order_ref = widget_order_ref
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
                prep_ref,
                state_ref,
                host_auth_ref,
                chatbot_adapter_auth_ref,
                widget_order_ref,
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
        ],
        attempt=attempt,
    )
    state.validation_run = validation_run
    state.prep_ref = prep_ref
    state.state_ref = state_ref
    state.chatbot_runtime_boot_ref = chatbot_runtime_boot_ref
    state.host_auth_ref = host_auth_ref
    state.chatbot_adapter_auth_ref = chatbot_adapter_auth_ref
    state.widget_order_ref = widget_order_ref
    state.validation_ref = validation_ref
    state.latest_failure_signature = None


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
        "apply": state.apply_ref,
        "export": state.export_bundle_ref,
        "validation": state.validation_ref,
    }
    return {stage: ref.version for stage, ref in mapping.items() if ref is not None}


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


def _clear_state_for_failure(*, state: _RunState, failed_stage: str, rewind_to: str) -> None:
    _clear_from_stage(state, failed_stage)
    if rewind_to != "validation":
        _clear_from_stage(state, rewind_to)


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
        _clear_from_stage(state, "apply")
        return
    if stage == "apply":
        state.apply_result = None
        state.apply_ref = None
        state.compile_preflight_ref = None
        state.compile_preflight_result = None
        _clear_from_stage(state, "export")
        return
    if stage == "export":
        state.patch_ref = None
        state.chatbot_patch_ref = None
        state.replay_result = None
        state.replay_ref = None
        state.export_bundle_ref = None
        _clear_from_stage(state, "validation")
        return
    if stage == "validation":
        state.validation_run = None
        state.prep_ref = None
        state.state_ref = None
        state.chatbot_runtime_boot_ref = None
        state.host_auth_ref = None
        state.chatbot_adapter_auth_ref = None
        state.widget_order_ref = None
        state.validation_ref = None


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
    notes_append = str(overrides.get("planning_notes_append") or "").strip()
    rationale = list(plan.planning_notes.llm_rationale)
    if notes_append:
        rationale.append(notes_append)
    return plan.model_copy(
        update={
            "host_backend": plan.host_backend.model_copy(update=backend_override),
            "host_frontend": plan.host_frontend.model_copy(update=frontend_override),
            "chatbot_bridge": plan.chatbot_bridge.model_copy(update=chatbot_override),
            "planning_notes": plan.planning_notes.model_copy(
                update={"llm_rationale": rationale}
            ),
        }
    )
