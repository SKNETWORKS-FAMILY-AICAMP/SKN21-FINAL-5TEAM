from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.planning import build_integration_plan
from chatbot.src.onboarding_v2.storage import ArtifactStore, DebugStore, EventStore, ViewProjector
from chatbot.src.onboarding_v2.validation.runner import run_validation_cycle


def run_onboarding_generation_v2(
    *,
    site: str,
    source_root: str,
    generated_root: str,
    runtime_root: str,
    run_id: str,
    agent_version: str = "dev",
    onboarding_credentials: dict[str, str] | None = None,
    **_: Any,
) -> dict[str, Any]:
    run_root = Path(generated_root) / site / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    event_store = EventStore(run_root)
    artifact_store = ArtifactStore(run_root)
    DebugStore(run_root)
    view_projector = ViewProjector(run_root)
    _write_run_metadata(
        run_root=run_root,
        site=site,
        source_root=source_root,
        run_id=run_id,
        agent_version=agent_version,
    )
    _write_manifest(
        run_root=run_root,
        site=site,
        source_root=source_root,
        run_id=run_id,
        credentials=onboarding_credentials or {},
    )

    analysis_started = event_store.write_event(
        run_id=run_id,
        stage="analysis",
        phase="start",
        event_type="stage_started",
        summary="analysis started",
    )
    snapshot = build_analysis_snapshot(site=site, source_root=source_root)
    analysis_ref = artifact_store.write_json_artifact(
        stage="analysis",
        artifact_type="snapshot",
        payload=snapshot.model_dump(mode="json"),
        producer="analyzer",
        event_ref=analysis_started.event_id,
    )
    event_store.write_event(
        run_id=run_id,
        stage="analysis",
        phase="finish",
        event_type="stage_completed",
        summary="analysis completed",
        artifact_refs=[analysis_ref],
    )

    planning_started = event_store.write_event(
        run_id=run_id,
        stage="planning",
        phase="start",
        event_type="stage_started",
        summary="planning started",
        input_refs=[analysis_ref],
    )
    plan = build_integration_plan(snapshot)
    plan_ref = artifact_store.write_json_artifact(
        stage="planning",
        artifact_type="integration-plan",
        payload=plan.model_dump(mode="json"),
        producer="planner",
        input_artifact_refs=[analysis_ref],
        event_ref=planning_started.event_id,
    )
    event_store.write_event(
        run_id=run_id,
        stage="planning",
        phase="finish",
        event_type="stage_completed",
        summary="planning completed",
        artifact_refs=[plan_ref],
        input_refs=[analysis_ref],
    )

    compile_started = event_store.write_event(
        run_id=run_id,
        stage="compile",
        phase="start",
        event_type="stage_started",
        summary="compile started",
        input_refs=[analysis_ref, plan_ref],
    )
    edit_program = compile_plan(snapshot=snapshot, plan=plan, source_root=source_root)
    compile_ref = artifact_store.write_json_artifact(
        stage="compile",
        artifact_type="edit-program",
        payload=edit_program.model_dump(mode="json"),
        producer="compiler",
        input_artifact_refs=[analysis_ref, plan_ref],
        event_ref=compile_started.event_id,
    )
    event_store.write_event(
        run_id=run_id,
        stage="compile",
        phase="finish",
        event_type="stage_completed",
        summary="compile completed",
        artifact_refs=[compile_ref],
        input_refs=[analysis_ref, plan_ref],
    )

    apply_started = event_store.write_event(
        run_id=run_id,
        stage="apply",
        phase="start",
        event_type="stage_started",
        summary="apply started",
        input_refs=[compile_ref],
    )
    apply_result = apply_edit_program(
        source_root=source_root,
        runtime_root=runtime_root,
        site=site,
        run_id=run_id,
        edit_program=edit_program,
    )
    apply_ref = artifact_store.write_json_artifact(
        stage="apply",
        artifact_type="apply-result",
        payload=apply_result.model_dump(mode="json"),
        producer="executor",
        input_artifact_refs=[compile_ref],
        event_ref=apply_started.event_id,
        status="completed" if apply_result.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="apply",
        phase="finish",
        event_type="stage_completed",
        summary="apply completed" if apply_result.passed else "apply failed",
        artifact_refs=[apply_ref],
        input_refs=[compile_ref],
    )

    export_started = event_store.write_event(
        run_id=run_id,
        stage="export",
        phase="start",
        event_type="stage_started",
        summary="export replay started",
        input_refs=[apply_ref],
    )
    patch_ref, replay_result, replay_ref = export_and_replay(
        source_root=source_root,
        runtime_workspace=apply_result.workspace_path,
        runtime_root=runtime_root,
        run_root=run_root,
        site=site,
        run_id=run_id,
        artifact_store=artifact_store,
    )
    export_bundle_ref = artifact_store.write_json_artifact(
        stage="export",
        artifact_type="export-bundle",
        payload={
            "patch_artifact": patch_ref.model_dump(mode="json"),
            "replay_artifact": replay_ref.model_dump(mode="json"),
            "replay_passed": replay_result.passed,
        },
        producer="exporter",
        input_artifact_refs=[apply_ref, patch_ref, replay_ref],
        event_ref=export_started.event_id,
        status="completed" if replay_result.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="export",
        phase="finish",
        event_type="stage_completed",
        summary="export replay completed" if replay_result.passed else "export replay failed",
        artifact_refs=[patch_ref, replay_ref, export_bundle_ref],
        input_refs=[apply_ref],
    )

    validation_started = event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="start",
        event_type="stage_started",
        summary="validation started",
        input_refs=[analysis_ref, plan_ref, compile_ref, apply_ref, replay_ref],
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="prep_start",
        event_type="backend_runtime_prep_started",
        summary="backend runtime prep started",
        input_refs=[analysis_ref, plan_ref, apply_ref],
    )
    validation_run = run_validation_cycle(
        run_root=run_root,
        runtime_workspace=apply_result.workspace_path,
        snapshot=snapshot,
        plan=plan,
        replay_result=replay_result,
        artifact_refs={
            "analysis": analysis_ref,
            "planning": plan_ref,
            "compile": compile_ref,
            "apply": apply_ref,
            "replay": replay_ref,
        },
        onboarding_credentials=onboarding_credentials,
    )
    prep_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="backend-runtime-prep",
        payload=validation_run.backend_runtime_prep.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[analysis_ref, plan_ref, apply_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.backend_runtime_prep.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="prep_finish",
        event_type="backend_runtime_prep_completed",
        summary="backend runtime prep completed" if validation_run.backend_runtime_prep.passed else "backend runtime prep failed",
        artifact_refs=[prep_ref],
        input_refs=[analysis_ref, plan_ref, apply_ref],
        failure_signature=(
            None
            if validation_run.backend_runtime_prep.passed
            else "backend_runtime_prep_failed"
        ),
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="boot_start",
        event_type="backend_runtime_boot_started",
        summary="backend runtime boot started",
        input_refs=[prep_ref],
    )
    state_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="backend-runtime-state",
        payload=validation_run.backend_runtime_state.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[prep_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.backend_runtime_state.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="boot_finish",
        event_type="backend_runtime_boot_completed",
        summary="backend runtime boot completed" if validation_run.backend_runtime_state.passed else "backend runtime boot failed",
        artifact_refs=[state_ref],
        input_refs=[prep_ref],
        failure_signature=(
            None
            if validation_run.backend_runtime_state.passed
            else "backend_runtime_boot_failed"
        ),
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="smoke_start",
        event_type="smoke_started",
        summary="smoke started",
        input_refs=[state_ref],
    )
    smoke_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="smoke-results",
        payload=validation_run.smoke_results.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[state_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_run.smoke_results.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="smoke_finish",
        event_type="smoke_completed",
        summary="smoke completed" if validation_run.smoke_results.passed else "smoke failed",
        artifact_refs=[smoke_ref],
        input_refs=[state_ref],
        failure_signature=(
            None
            if validation_run.smoke_results.passed
            else "smoke_failed"
        ),
    )
    validation_bundle = validation_run.bundle
    validation_ref = artifact_store.write_json_artifact(
        stage="validation",
        artifact_type="validation-bundle",
        payload=validation_bundle.model_dump(mode="json"),
        producer="validator",
        input_artifact_refs=[analysis_ref, plan_ref, compile_ref, apply_ref, replay_ref, prep_ref, state_ref, smoke_ref],
        event_ref=validation_started.event_id,
        status="completed" if validation_bundle.passed else "failed",
    )
    event_store.write_event(
        run_id=run_id,
        stage="validation",
        phase="finish",
        event_type="stage_completed",
        summary="validation completed" if validation_bundle.passed else "validation failed",
        artifact_refs=[validation_ref],
        input_refs=[analysis_ref, plan_ref, compile_ref, apply_ref, replay_ref],
        failure_signature=validation_bundle.failure_signature,
    )

    final_status = "exported" if validation_bundle.passed and replay_result.passed and apply_result.passed else "failed"
    view_projector.project(
        run_id=run_id,
        site=site,
        status=final_status,
        latest_failure_signature=validation_bundle.failure_signature,
    )
    return {
        "engine": "v2",
        "run_root": str(run_root),
        "status": final_status,
        "runtime_workspace": apply_result.workspace_path,
        "latest_analysis_artifact": _artifact_abspath(run_root, "analysis", "snapshot", analysis_ref.path),
        "latest_plan_artifact": _artifact_abspath(run_root, "planning", "integration-plan", plan_ref.path),
        "latest_compile_artifact": _artifact_abspath(run_root, "compile", "edit-program", compile_ref.path),
        "latest_apply_artifact": _artifact_abspath(run_root, "apply", "apply-result", apply_ref.path),
        "latest_validation_artifact": _artifact_abspath(run_root, "validation", "validation-bundle", validation_ref.path),
        "latest_export_artifact": _artifact_abspath(run_root, "export", "export-bundle", export_bundle_ref.path),
        "approved_patch_path": _artifact_abspath(run_root, "export", "approved-patch", patch_ref.path),
        "latest_replay_artifact": _artifact_abspath(run_root, "export", "replay-result", replay_ref.path),
        "failure_signature": validation_bundle.failure_signature,
    }


def _artifact_abspath(run_root: Path, stage: str, artifact_type: str, filename: str) -> str:
    stage_dir = {
        "analysis": "01-analysis",
        "planning": "02-planning",
        "compile": "03-compile",
        "apply": "04-apply",
        "validation": "05-validation",
        "export": "06-export",
    }[stage]
    return str(run_root / "artifacts" / stage_dir / artifact_type / filename)


def _write_run_metadata(
    *,
    run_root: Path,
    site: str,
    source_root: str,
    run_id: str,
    agent_version: str,
) -> None:
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "site": site,
                "source_root": source_root,
                "run_id": run_id,
                "engine": "v2",
                "agent_version": agent_version,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_manifest(
    *,
    run_root: Path,
    site: str,
    source_root: str,
    run_id: str,
    credentials: dict[str, str],
) -> None:
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "site": site,
                "source_root": source_root,
                "run_id": run_id,
                "credentials": credentials,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
