from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from chatbot.src.onboarding_v2.eventing import EventCallback
from chatbot.src.onboarding_v2.models.common import DebugRecord
from chatbot.src.onboarding_v2.models.repair import FailureBundle, RepairDecision
from chatbot.src.onboarding_v2.llm_runtime import invoke_structured_stage
from chatbot.src.onboarding_v2.stage_tools import build_repair_tool_runtime
from chatbot.src.onboarding_v2.storage import DebugStore

_REPAIR_SYSTEM_PROMPT = """You are the RepairAgent diagnose phase for the onboarding_v2 pipeline.
Return only JSON with these keys:
- failure_signature
- diagnosis
- rewind_to
- preserve_artifacts
- required_rechecks
- additional_discovery
- artifact_overrides
- stop
- stop_reason

Rules:
- rewind_to must be one of: validation, compile, planning, analysis.
- preserve_artifacts must contain only stage names.
- additional_discovery must be an array of objects with keys path and reason.
- artifact_overrides must be a JSON object.
- If the failure can be retried without changing strategy, prefer validation.
- Compile-stage failures that mention compile-preflight, host-import-smoke, banned imports, server_fastapi import failures, chatbot_runtime_import*, or host_backend_import* are import-graph defects. Prefer rewind_to=compile with required_rechecks including compile_preflight.
- If strategy or target changes are required, use planning or analysis.
- If you cannot diagnose safely, set stop=true and stop_reason to a short machine-friendly reason.
Do not include markdown."""


def _is_compile_import_graph_failure(failure_bundle: FailureBundle) -> bool:
    if failure_bundle.failed_stage != "compile":
        return False
    artifact_types = {artifact.artifact_type for artifact in failure_bundle.related_artifacts}
    haystack = (
        f"{failure_bundle.failure_signature}\n"
        f"{failure_bundle.failure_summary}"
    ).lower()
    if "compile-preflight" in artifact_types or "host-import-smoke" in artifact_types:
        return True
    return (
        "chatbot_runtime_import" in haystack
        or "host_backend_import" in haystack
        or "banned import" in haystack
    )


def _build_compile_import_graph_decision(failure_bundle: FailureBundle) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "compile import-graph defect detected from compile preflight; "
            "rewind to compile and rerun compile_preflight"
        ),
        rewind_to="compile",
        preserve_artifacts=["analysis", "planning"],
        required_rechecks=["compile_preflight"],
        additional_discovery=[],
        artifact_overrides={},
        stop=False,
        stop_reason=None,
    )


def _iter_validation_contexts(
    validation_payload: dict[str, Any],
) -> list[tuple[str | None, dict[str, Any]]]:
    if not isinstance(validation_payload, dict):
        return []
    contexts: list[tuple[str | None, dict[str, Any]]] = [(None, validation_payload)]
    for raw_check in list(validation_payload.get("checks") or []):
        if not isinstance(raw_check, dict):
            continue
        details = raw_check.get("details")
        if not isinstance(details, dict):
            continue
        check_name = str(raw_check.get("name") or "").strip() or None
        contexts.append((check_name, details))
    return contexts


def _is_platform_validation_failure(
    failure_bundle: FailureBundle,
    validation_payload: dict[str, Any],
) -> bool:
    if failure_bundle.failed_stage != "validation":
        return False
    return any(
        str(context.get("failure_origin") or "").strip() == "platform_validation"
        for _, context in _iter_validation_contexts(validation_payload)
    )


def _build_platform_validation_decision(failure_bundle: FailureBundle) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "validation platform defect detected from structured failure metadata; "
            "stop repair and preserve generated artifacts for validator fixes"
        ),
        rewind_to="validation",
        preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
        required_rechecks=[],
        additional_discovery=[],
        artifact_overrides={},
        stop=True,
        stop_reason="platform_validation_bug",
    )


def _is_host_external_dependency_failure(
    failure_bundle: FailureBundle,
    validation_payload: dict[str, Any],
) -> bool:
    if failure_bundle.failed_stage != "validation":
        return False
    return any(
        str(context.get("failure_origin") or "").strip() == "host_contract"
        and str(context.get("failure_code") or "").strip()
        == "backend_runtime_prep_external_dependency_unavailable"
        for _, context in _iter_validation_contexts(validation_payload)
    )


def _build_host_external_dependency_decision(
    failure_bundle: FailureBundle,
) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "external host dependency unavailable during backend fixture prep; "
            "stop repair and preserve generated artifacts until the host contract is satisfied"
        ),
        rewind_to="validation",
        preserve_artifacts=["analysis", "planning", "compile", "apply", "export", "indexing"],
        required_rechecks=["backend_runtime_prep"],
        additional_discovery=[],
        artifact_overrides={},
        stop=True,
        stop_reason="host_external_dependency_unavailable",
    )


def _is_host_auth_bootstrap_failure(
    failure_bundle: FailureBundle,
    validation_payload: dict[str, Any],
) -> bool:
    if failure_bundle.failed_stage != "validation":
        return False
    for check_name, context in _iter_validation_contexts(validation_payload):
        if (
            check_name == "host_auth_bootstrap"
            and str(context.get("failure_origin") or "").strip() == "host_contract"
        ):
            return True
    haystack = (
        f"{failure_bundle.failure_signature}\n"
        f"{failure_bundle.failure_summary}"
    ).lower()
    tokens = (
        "host_auth_bootstrap",
        "host login failed",
        "bootstrap contract",
        "bootstrap missing",
        "missing site_id",
        "missing user.id",
        "missing access_token",
        "missing authenticated=true",
    )
    return any(token in haystack for token in tokens)


def _build_host_auth_bootstrap_decision(failure_bundle: FailureBundle) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "host auth bootstrap contract/login failure detected during validation; "
            "rerun validation and recheck host_auth_bootstrap before considering compile changes"
        ),
        rewind_to="validation",
        preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
        required_rechecks=["host_auth_bootstrap"],
        additional_discovery=[],
        artifact_overrides={},
        stop=False,
        stop_reason=None,
    )


def diagnose_failure(
    *,
    failure_bundle: FailureBundle,
    analysis_bundle_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
    planning_bundle_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    edit_program_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    llm_provider: str,
    llm_model: str,
    debug_store: DebugStore,
    llm_factory: Callable[[], Any] | None = None,
    event_callback: EventCallback | None = None,
    heartbeat_interval_s: float = 5.0,
) -> RepairDecision:
    payload = {
        "failure_bundle": failure_bundle.model_dump(mode="json"),
        "analysis_bundle": analysis_bundle_payload,
        "snapshot": snapshot_payload,
        "planning_bundle": planning_bundle_payload,
        "plan": plan_payload,
        "edit_program": edit_program_payload,
        "validation": validation_payload,
    }
    if _is_compile_import_graph_failure(failure_bundle):
        decision = _build_compile_import_graph_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "compile_import_graph_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    if _is_platform_validation_failure(failure_bundle, validation_payload):
        decision = _build_platform_validation_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "platform_validation_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    if _is_host_external_dependency_failure(failure_bundle, validation_payload):
        decision = _build_host_external_dependency_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "host_external_dependency_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    if _is_host_auth_bootstrap_failure(failure_bundle, validation_payload):
        decision = _build_host_auth_bootstrap_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "host_auth_bootstrap_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    fallback_decision = RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis="repair llm unavailable",
        rewind_to="validation",
        preserve_artifacts=[],
        required_rechecks=[],
        additional_discovery=[],
        artifact_overrides={},
        stop=True,
        stop_reason="repair_llm_unavailable",
    )
    llm_builder = None
    if llm_factory is not None:
        llm_builder = lambda provider, model, temperature: llm_factory()
    source_root = (
        snapshot_payload.get("repo_profile", {}).get("source_root")
        if isinstance(snapshot_payload.get("repo_profile"), dict)
        else None
    )
    repair_root = Path(source_root).resolve() if str(source_root or "").strip() else Path.cwd()
    tool_runtime = build_repair_tool_runtime(
        root=repair_root,
        failure_bundle=failure_bundle,
        analysis_bundle_payload=analysis_bundle_payload,
    )
    return invoke_structured_stage(
        stage="repair",
        phase="diagnosis",
        provider=llm_provider,
        model=llm_model,
        system_prompt=_REPAIR_SYSTEM_PROMPT,
        payload=payload,
        response_model=RepairDecision,
        fallback_payload=fallback_decision.model_dump(mode="json"),
        attempt=failure_bundle.attempt_number,
        debug_store=debug_store,
        llm_builder=llm_builder,
        artifact_refs=failure_bundle.related_artifacts,
        tool_runtime=tool_runtime,
        event_callback=event_callback,
        heartbeat_interval_s=heartbeat_interval_s,
    )
