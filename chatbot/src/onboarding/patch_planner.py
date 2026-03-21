from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from chatbot.src.graph.llm_providers import make_chat_llm

from .debug_logging import (
    append_generation_log,
    append_llm_usage,
    append_onboarding_event,
    append_recovery_event,
    extract_llm_usage,
    write_llm_debug_artifact,
)
from .frontend_generator import build_frontend_mount_contract
from .framework_strategies import (
    build_strategy_allowlist,
    seam_target_rejection_reason,
    select_strategy_target_candidates,
)

_UNIFIED_DIFF_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@")


class PatchProposalTarget(BaseModel):
    path: str
    reason: str
    intent: str
    insertion_hint: dict[str, Any] | None = None


class PatchProposalPayload(BaseModel):
    target_files: list[PatchProposalTarget]
    supporting_generated_files: list[str]
    recommended_outputs: list[str]
    analysis_summary: dict[str, Any]


def write_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    output_path: str | Path,
) -> Path:
    payload = build_patch_proposal(
        analysis=analysis,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_llm_first_patch_proposal(
    *,
    source_root: str | Path,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    llm_codebase_interpretation: dict[str, Any] | None = None,
    output_path: str | Path,
    execution_output_path: str | Path,
    llm_factory: Callable[[], Any],
    provider: str | None = None,
    model: str | None = None,
) -> Path:
    fallback_payload = build_patch_proposal(
        analysis=analysis,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
        llm_codebase_interpretation=llm_codebase_interpretation,
    )
    payload = fallback_payload
    source = "hard_fallback"
    fallback_reason = "llm_exception"
    recovery_reason: str | None = None
    hard_fallback_reason: str | None = "llm_exception"
    raw_response_content: str | None = None
    parsed_payload: Any = None
    error_type: str | None = None
    error_message: str | None = None
    rejection_reason: dict[str, Any] | None = None
    retry_rejection_reason: dict[str, Any] | None = None
    retry_attempt_count = 0
    retry_source: str | None = None
    retry_raw_response_content: str | None = None
    report_root = Path(output_path).parent
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="patch_planner",
        stage="planning",
        event="llm_call_started",
        severity="info",
        summary="llm patch proposal started",
        source="llm",
        details={"provider": provider or "unknown", "model": model or "unknown"},
    )

    try:
        llm = llm_factory()
        initial_messages = [
            SystemMessage(content=_llm_patch_proposal_system_prompt()),
            HumanMessage(
                content=json.dumps(
                    {
                        "source_root": str(source_root),
                        "analysis": analysis,
                        "codebase_map": codebase_map,
                        "llm_codebase_interpretation": llm_codebase_interpretation,
                        "file_samples": _build_patch_proposal_file_samples(source_root, codebase_map),
                        "recommended_outputs": recommended_outputs,
                        "fallback_patch_proposal": fallback_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        ]
        response = llm.invoke(initial_messages)
        append_llm_usage(
            report_root=Path(output_path).parent,
            component="llm_patch_proposal",
            provider=provider,
            model=model or getattr(llm, "model_name", None),
            usage=extract_llm_usage(response),
        )
        raw_response_content = str(response.content)
        raw_payload = json.loads(raw_response_content)
        parsed_payload = raw_payload
        target_rejection_reason = None
        retry_payload = None
        retry_raw_response_content: str | None = None

        def _materialize_patch_proposal_response(
            response_payload: dict[str, Any],
        ) -> tuple[PatchProposalPayload, dict[str, Any], str | None, str | None]:
            materialized_source = "llm"
            materialized_recovery_reason: str | None = None
            parsed = response_payload
            try:
                llm_payload = PatchProposalPayload.model_validate(parsed)
            except ValidationError:
                recovered = _recover_patch_proposal_payload(
                    parsed,
                    analysis=analysis,
                    codebase_map=codebase_map,
                    recommended_outputs=recommended_outputs,
                    fallback_payload=fallback_payload,
                )
                if recovered is None:
                    raise
                parsed, materialized_recovery_reason = recovered
                llm_payload = PatchProposalPayload.model_validate(parsed)
                materialized_source = "recovered_llm"
            return llm_payload, parsed, materialized_source, materialized_recovery_reason

        llm_payload, parsed_payload, source, recovery_reason = _materialize_patch_proposal_response(raw_payload)
        target_rejection_reason = _build_llm_patch_proposal_target_rejection(
            llm_payload=llm_payload,
            codebase_map=codebase_map,
            recommended_outputs=recommended_outputs,
        )
        if target_rejection_reason is not None:
            rejection_reason = target_rejection_reason
            retry_attempt_count = 1
            retry_source = source
            retry_messages = [
                SystemMessage(content=_llm_patch_proposal_system_prompt()),
                HumanMessage(
                    content=_llm_patch_proposal_retry_human_payload(
                        source_root=source_root,
                        analysis=analysis,
                        codebase_map=codebase_map,
                        llm_codebase_interpretation=llm_codebase_interpretation,
                        recommended_outputs=recommended_outputs,
                        fallback_payload=fallback_payload,
                        previous_patch_proposal=llm_payload.model_dump(mode="json"),
                        guardrail_rejection=target_rejection_reason,
                    )
                ),
            ]
            retry_response = llm.invoke(retry_messages)
            append_llm_usage(
                report_root=Path(output_path).parent,
                component="llm_patch_proposal",
                provider=provider,
                model=model or getattr(llm, "model_name", None),
                usage=extract_llm_usage(retry_response),
            )
            retry_raw_response_content = str(retry_response.content)
            retry_raw_payload = json.loads(retry_raw_response_content)
            parsed_payload = retry_raw_payload
            retry_payload, parsed_payload, retry_source, retry_recovery_reason = _materialize_patch_proposal_response(retry_raw_payload)
            retry_rejection_reason = _build_llm_patch_proposal_target_rejection(
                llm_payload=retry_payload,
                codebase_map=codebase_map,
                recommended_outputs=recommended_outputs,
            )
            if retry_rejection_reason is None:
                payload = retry_payload.model_dump(mode="json")
                source = "recovered_llm"
                if retry_recovery_reason is not None:
                    recovery_reason = retry_recovery_reason
                else:
                    recovery_reason = "patch_proposal_guardrail_retry_succeeded"
                fallback_reason = None
                hard_fallback_reason = None
            else:
                fallback_reason = "invalid_target_selection"
                hard_fallback_reason = "invalid_target_selection"
                error_type = "invalid_target_selection"
                error_message = retry_rejection_reason["message"]
                payload = fallback_payload
                source = "hard_fallback"
        else:
            payload = llm_payload.model_dump(mode="json")
            if source != "recovered_llm":
                source = "llm"
            fallback_reason = None
            if source == "llm":
                recovery_reason = None
            hard_fallback_reason = None
    except json.JSONDecodeError as exc:
        fallback_reason = "invalid_llm_response"
        hard_fallback_reason = "invalid_llm_response"
        error_type = "invalid_llm_response"
        error_message = str(exc)
    except ValidationError as exc:
        fallback_reason = "invalid_llm_payload"
        hard_fallback_reason = "invalid_llm_payload"
        error_type = "invalid_llm_payload"
        error_message = str(exc)
    except ValueError as exc:
        fallback_reason = "invalid_target_selection"
        hard_fallback_reason = "invalid_target_selection"
        error_type = "invalid_target_selection"
        error_message = str(exc)
    except Exception as exc:
        fallback_reason = "llm_exception"
        hard_fallback_reason = "llm_exception"
        error_type = "llm_exception"
        error_message = str(exc)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    execution_path = Path(execution_output_path)
    execution_path.parent.mkdir(parents=True, exist_ok=True)
    execution_path.write_text(
        json.dumps(
            {
                "source": source,
                "fallback_reason": fallback_reason,
                "recovery_reason": recovery_reason,
                "hard_fallback_reason": hard_fallback_reason,
                "rejection_reason": rejection_reason,
                "retry_rejection_reason": retry_rejection_reason,
                "retry_attempt_count": retry_attempt_count,
                "retry_source": retry_source,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    debug_payload = {
        "status": source,
        "fallback_reason": fallback_reason,
        "recovery_reason": recovery_reason,
        "hard_fallback_reason": hard_fallback_reason,
        "rejection_reason": rejection_reason,
        "retry_rejection_reason": retry_rejection_reason,
        "raw_response": raw_response_content,
        "retry_raw_response": retry_raw_response_content,
        "parsed_payload": parsed_payload,
        "error_type": error_type,
        "error_message": error_message,
        "attempt_count": 1 + retry_attempt_count,
        "retry_attempt_count": retry_attempt_count,
        "retry_source": retry_source,
    }
    debug_path = write_llm_debug_artifact(
        report_root=execution_path.parent,
        name="patch-proposal",
        payload=debug_payload,
    )
    append_onboarding_event(
        report_root=execution_path.parent,
        run_id="unknown",
        component="patch_planner",
        stage="planning",
        event="artifact_written",
        severity="info",
        summary="patch proposal execution artifact written",
        source=source,
        details={"artifact_kind": "execution_metadata", "output_path": str(execution_path)},
    )
    append_onboarding_event(
        report_root=execution_path.parent,
        run_id="unknown",
        component="patch_planner",
        stage="planning",
        event="artifact_written",
        severity="info",
        summary="patch proposal debug artifact written",
        source=source,
        details={"artifact_kind": "llm_debug"},
        debug_artifact_path=str(debug_path),
    )
    if source in {"recovered_llm", "hard_fallback"}:
        append_generation_log(
            report_root=execution_path.parent,
            level="WARN",
            component="patch_planner",
            event="recovery_started",
            message="patch proposal recovery started",
            details={
                "source": source,
                "recovery_reason": recovery_reason,
                "hard_fallback_reason": hard_fallback_reason,
            },
        )
        append_generation_log(
            report_root=execution_path.parent,
            level="INFO" if source == "recovered_llm" else "WARN",
            component="patch_planner",
            event="recovery_succeeded" if source == "recovered_llm" else "hard_fallback_used",
            message="patch proposal recovered" if source == "recovered_llm" else "patch proposal used hard fallback",
            details={
                "source": source,
                "recovery_reason": recovery_reason,
                "hard_fallback_reason": hard_fallback_reason,
            },
        )
        append_recovery_event(
            report_root=execution_path.parent,
            component="llm_patch_proposal",
            source=source,
            recovery_reason=recovery_reason,
            hard_fallback_reason=hard_fallback_reason,
        )
    if source in {"llm", "recovered_llm"}:
        append_onboarding_event(
            report_root=execution_path.parent,
            run_id="unknown",
            component="patch_planner",
            stage="planning",
            event="llm_output_accepted",
            severity="info",
            summary="llm patch proposal accepted",
            source=source,
            recovery={"applied": source == "recovered_llm", "reason": recovery_reason} if source == "recovered_llm" else None,
            details={"output_path": str(path)},
            debug_artifact_path=str(debug_path),
        )
    else:
        append_onboarding_event(
            report_root=execution_path.parent,
            run_id="unknown",
            component="patch_planner",
            stage="planning",
            event="hard_fallback_used",
            severity="warn",
            summary="llm patch proposal used hard fallback",
            source="hard_fallback",
            recovery={"applied": False, "reason": hard_fallback_reason},
            details={"failure_reason": hard_fallback_reason, "output_path": str(path)},
            debug_artifact_path=str(debug_path),
        )
    append_generation_log(
        report_root=execution_path.parent,
        level="INFO" if source == "llm" else "WARN",
        component="patch_planner",
        event="llm_patch_proposal_completed" if source == "llm" else "llm_patch_proposal_recovered" if source == "recovered_llm" else "llm_patch_proposal_hard_fallback",
        message="llm patch proposal finished" if source == "llm" else "llm patch proposal recovered" if source == "recovered_llm" else "llm patch proposal used hard fallback",
        details={
            "source": source,
            "fallback_reason": fallback_reason,
            "recovery_reason": recovery_reason,
            "hard_fallback_reason": hard_fallback_reason,
            "debug_path": str(debug_path),
            "execution_path": str(execution_path),
        },
    )
    return path


def write_llm_patch_draft(
    *,
    source_root: str | Path,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    patch_proposal: dict[str, Any],
    output_path: str | Path,
    llm_factory: Callable[[], Any],
    provider: str | None = None,
    model: str | None = None,
) -> Path:
    report_root = Path(output_path).parent.parent / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    append_generation_log(
        report_root=report_root,
        level="INFO",
        component="patch_planner",
        event="llm_patch_draft_started",
        message="starting llm patch draft generation",
        details={"output_path": str(output_path)},
    )
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="patch_planner",
        stage="generation",
        event="llm_call_started",
        severity="info",
        summary="llm patch draft started",
        source="llm",
        details={"output_path": str(output_path), "provider": provider or "unknown", "model": model or "unknown"},
    )
    llm = llm_factory()
    initial_messages = [
        SystemMessage(content=_llm_patch_system_prompt()),
        HumanMessage(
            content=json.dumps(
                {
                    "source_root": str(source_root),
                    "analysis": analysis,
                    "codebase_map": codebase_map,
                    "patch_proposal": patch_proposal,
                },
                ensure_ascii=False,
                indent=2,
            )
        ),
    ]
    response = llm.invoke(initial_messages)
    append_llm_usage(
        report_root=report_root,
        component="llm_patch_draft",
        provider=provider,
        model=model or getattr(llm, "model_name", None),
        usage=extract_llm_usage(response),
    )

    attempts: list[dict[str, Any]] = []
    first_raw_content = str(response.content)
    first_attempt = _prepare_llm_patch_attempt(first_raw_content, patch_proposal=patch_proposal)
    attempts.append(first_attempt)
    final_attempt = first_attempt

    retry_validation_error: dict[str, str] | None = None
    if first_attempt["validation_error"] is not None and first_attempt["validation_error"]["reason"] == "invalid_patch_format":
        retry_messages = [
            SystemMessage(content=_llm_patch_system_prompt()),
            HumanMessage(
                content=_llm_patch_retry_human_payload(
                    source_root=source_root,
                    analysis=analysis,
                    codebase_map=codebase_map,
                    patch_proposal=patch_proposal,
                    previous_patch=first_attempt["normalized_response"],
                    validation_error=first_attempt["validation_error"],
                )
            ),
        ]
        retry_response = llm.invoke(retry_messages)
        append_llm_usage(
            report_root=report_root,
            component="llm_patch_draft",
            provider=provider,
            model=model or getattr(llm, "model_name", None),
            usage=extract_llm_usage(retry_response),
        )
        retry_attempt = _prepare_llm_patch_attempt(str(retry_response.content), patch_proposal=patch_proposal)
        attempts.append(retry_attempt)
        final_attempt = retry_attempt
        retry_validation_error = retry_attempt["validation_error"]

    content = str(final_attempt["normalized_response"])
    recovery_reason = final_attempt["recovery_reason"]
    debug_payload: dict[str, Any] = {
        "status": "recovered_llm" if recovery_reason else "llm",
        "final_status": "recovered_llm" if recovery_reason else "llm",
        "fallback_reason": None,
        "recovery_reason": recovery_reason,
        "hard_fallback_reason": None,
        "raw_response": first_raw_content,
        "normalized_response": content,
        "error_type": None,
        "error_message": None,
        "attempt_count": len(attempts),
        "retry_error_type": retry_validation_error["reason"] if retry_validation_error is not None else None,
        "retry_error_message": retry_validation_error["message"] if retry_validation_error is not None else None,
    }
    execution_payload = {
        "source": "recovered_llm" if recovery_reason else "llm",
        "fallback_reason": None,
        "recovery_reason": recovery_reason,
        "hard_fallback_reason": None,
        "attempt_count": len(attempts),
    }
    validation_error = final_attempt["validation_error"]
    if validation_error is not None:
        execution_payload = {
            "source": "hard_fallback",
            "fallback_reason": validation_error["reason"],
            "recovery_reason": None,
            "hard_fallback_reason": validation_error["reason"],
            "attempt_count": len(attempts),
        }
        debug_payload["status"] = "hard_fallback"
        debug_payload["final_status"] = "hard_fallback"
        debug_payload["fallback_reason"] = validation_error["reason"]
        debug_payload["recovery_reason"] = None
        debug_payload["hard_fallback_reason"] = validation_error["reason"]
        debug_payload["error_type"] = validation_error["reason"]
        debug_payload["error_message"] = validation_error["message"]
        content = _build_llm_patch_placeholder(
            reason=validation_error["reason"],
            message=validation_error["message"],
        )
    elif len(attempts) == 2 and first_attempt["validation_error"] is not None:
        execution_payload["source"] = "recovered_llm"
        execution_payload["recovery_reason"] = "invalid_patch_format_retry_succeeded"
        debug_payload["status"] = "recovered_llm"
        debug_payload["final_status"] = "recovered_llm"
        debug_payload["recovery_reason"] = "invalid_patch_format_retry_succeeded"
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    execution_path = report_root / "llm-patch-draft-execution.json"
    execution_path.write_text(json.dumps(execution_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="patch_planner",
        stage="generation",
        event="artifact_written",
        severity="info",
        summary="patch draft execution artifact written",
        source=execution_payload["source"],
        details={"artifact_kind": "execution_metadata", "output_path": str(execution_path)},
    )
    if execution_payload["source"] in {"recovered_llm", "hard_fallback"}:
        append_generation_log(
            report_root=report_root,
            level="WARN",
            component="patch_planner",
            event="recovery_started",
            message="patch draft recovery started",
            details={
                "source": execution_payload["source"],
                "recovery_reason": execution_payload.get("recovery_reason"),
                "hard_fallback_reason": execution_payload.get("hard_fallback_reason"),
            },
        )
        append_generation_log(
            report_root=report_root,
            level="INFO" if execution_payload["source"] == "recovered_llm" else "WARN",
            component="patch_planner",
            event="recovery_succeeded" if execution_payload["source"] == "recovered_llm" else "hard_fallback_used",
            message="patch draft recovered" if execution_payload["source"] == "recovered_llm" else "patch draft used hard fallback",
            details={
                "source": execution_payload["source"],
                "recovery_reason": execution_payload.get("recovery_reason"),
                "hard_fallback_reason": execution_payload.get("hard_fallback_reason"),
            },
        )
        append_recovery_event(
            report_root=report_root,
            component="llm_patch_draft",
            source=str(execution_payload["source"]),
            recovery_reason=execution_payload.get("recovery_reason"),
            hard_fallback_reason=execution_payload.get("hard_fallback_reason"),
        )
    debug_path = write_llm_debug_artifact(
        report_root=report_root,
        name="patch-draft",
        payload=debug_payload,
    )
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="patch_planner",
        stage="generation",
        event="artifact_written",
        severity="info",
        summary="patch draft debug artifact written",
        source=execution_payload["source"],
        details={"artifact_kind": "llm_debug"},
        debug_artifact_path=str(debug_path),
    )
    if execution_payload["source"] in {"llm", "recovered_llm"}:
        append_onboarding_event(
            report_root=report_root,
            run_id="unknown",
            component="patch_planner",
            stage="generation",
            event="llm_output_accepted",
            severity="info",
            summary="llm patch draft accepted",
            source=execution_payload["source"],
            recovery={
                "applied": execution_payload["source"] == "recovered_llm",
                "reason": execution_payload.get("recovery_reason"),
            } if execution_payload["source"] == "recovered_llm" else None,
            details={"output_path": str(path)},
            debug_artifact_path=str(debug_path),
        )
    else:
        append_onboarding_event(
            report_root=report_root,
            run_id="unknown",
            component="patch_planner",
            stage="generation",
            event="hard_fallback_used",
            severity="warn",
            summary="llm patch draft used hard fallback",
            source="hard_fallback",
            recovery={"applied": False, "reason": execution_payload.get("hard_fallback_reason")},
            details={"failure_reason": execution_payload.get("hard_fallback_reason"), "output_path": str(path)},
            debug_artifact_path=str(debug_path),
        )
    append_generation_log(
        report_root=report_root,
        level="INFO" if execution_payload["source"] == "llm" else "WARN",
        component="patch_planner",
        event="llm_patch_draft_completed" if execution_payload["source"] == "llm" else "llm_patch_draft_recovered" if execution_payload["source"] == "recovered_llm" else "llm_patch_draft_hard_fallback",
        message="llm patch draft finished" if execution_payload["source"] == "llm" else "llm patch draft recovered" if execution_payload["source"] == "recovered_llm" else "llm patch draft used hard fallback",
        details={
            "source": execution_payload["source"],
            "fallback_reason": execution_payload["fallback_reason"],
            "recovery_reason": execution_payload.get("recovery_reason"),
            "hard_fallback_reason": execution_payload.get("hard_fallback_reason"),
            "debug_path": str(debug_path),
            "execution_path": str(execution_path),
        },
    )
    return path


def write_patch_comparison_report(
    *,
    run_root: str | Path,
    output_path: str | Path,
) -> Path:
    root = Path(run_root)
    deterministic_path = root / "patches" / "proposed.patch"
    llm_path = root / "patches" / "llm-proposed.patch"
    deterministic_summary = _patch_summary(deterministic_path)
    llm_summary = _patch_summary(llm_path)
    deterministic_targets = set(deterministic_summary["target_files"])
    llm_targets = set(llm_summary["target_files"])
    deterministic_simulation = _read_json_if_exists(root / "reports" / "merge-simulation.json")
    llm_simulation = _read_json_if_exists(root / "reports" / "llm-patch-simulation.json")
    same_content = _read_optional_text(deterministic_path) == _read_optional_text(llm_path)

    payload = {
        "deterministic_patch": deterministic_summary,
        "llm_patch": llm_summary,
        "same_content": same_content,
        "line_count_delta": llm_summary["line_count"] - deterministic_summary["line_count"],
        "target_file_delta": {
            "only_in_deterministic": sorted(deterministic_targets - llm_targets),
            "only_in_llm": sorted(llm_targets - deterministic_targets),
        },
        "simulation": {
            "deterministic_passed": None if deterministic_simulation is None else bool(deterministic_simulation.get("passed")),
            "llm_passed": None if llm_simulation is None else bool(llm_simulation.get("passed")),
        },
        "recommended_source": _recommend_patch_source(
            deterministic_exists=bool(deterministic_summary["exists"]),
            llm_exists=bool(llm_summary["exists"]),
            same_content=same_content,
            deterministic_targets=deterministic_targets,
            llm_targets=llm_targets,
            deterministic_passed=None if deterministic_simulation is None else bool(deterministic_simulation.get("passed")),
            llm_passed=None if llm_simulation is None else bool(llm_simulation.get("passed")),
        ),
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_llm_patch_factory(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> Callable[[], Any]:
    return lambda: llm_builder(provider, model, 0)


def build_llm_patch_proposal_factory(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> Callable[[], Any]:
    return lambda: llm_builder(provider, model, 0)


def build_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    llm_codebase_interpretation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    integration_contract = (
        codebase_map.get("integration_contract")
        or analysis.get("integration_contract")
        or {}
    )
    strategy_allowlist = build_strategy_allowlist(
        integration_contract=integration_contract,
        recommended_outputs=recommended_outputs,
        codebase_map=codebase_map,
    )
    strategy_selected_targets = select_strategy_target_candidates(
        integration_contract=integration_contract,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
    )
    selected_targets = _select_target_candidates_from_map(
        codebase_map,
        llm_codebase_interpretation=llm_codebase_interpretation,
    )
    if strategy_selected_targets:
        if llm_codebase_interpretation and selected_targets:
            selected_targets = _merge_target_candidates(
                primary=selected_targets,
                secondary=strategy_selected_targets,
            )
        else:
            selected_targets = strategy_selected_targets
    if strategy_allowlist:
        selected_targets = _restrict_targets_to_strategy_allowlist(
            selected_targets=selected_targets,
            strategy_selected_targets=strategy_selected_targets,
            strategy_allowlist=strategy_allowlist,
            codebase_map=codebase_map,
        )
    selected_targets, target_rejections = _filter_seam_targets(selected_targets)
    target_files: list[dict[str, str]] = []
    for target in selected_targets:
        target_files.append(
            {
                "path": str(target.get("path") or ""),
                "reason": str(target.get("reason") or ""),
                "intent": _infer_intent(
                    path=str(target.get("path") or ""),
                    analysis=analysis,
                    recommended_outputs=recommended_outputs,
                ),
            }
        )

    supporting_generated_files = _supporting_files(recommended_outputs)
    return {
        "target_files": target_files,
        "supporting_generated_files": supporting_generated_files,
        "recommended_outputs": recommended_outputs,
        "analysis_summary": {
            "auth_style": ((analysis.get("auth") or {}).get("auth_style") or "unknown"),
            "frontend_mount_points": analysis.get("frontend_mount_points") or [],
            "route_prefixes": analysis.get("route_prefixes") or [],
            "backend_strategy": codebase_map.get("backend_strategy") or ((analysis.get("framework") or {}).get("backend") or "unknown"),
            "frontend_strategy": codebase_map.get("frontend_strategy") or ((analysis.get("framework") or {}).get("frontend") or "unknown"),
            "backend_route_targets": [
                str(item.get("path") or "")
                for item in (codebase_map.get("backend_route_targets") or [])
                if str(item.get("path") or "")
            ],
            "frontend_mount_targets": [
                str(item.get("path") or "")
                for item in (codebase_map.get("frontend_mount_targets") or [])
                if str(item.get("path") or "")
            ],
            "tool_registry_targets": [
                str(item.get("path") or "")
                for item in (codebase_map.get("tool_registry_targets") or [])
                if str(item.get("path") or "")
            ],
            "strategy_allowlist": sorted(strategy_allowlist),
            "target_rejections": target_rejections,
        },
    }


def _merge_target_candidates(
    *,
    primary: list[dict[str, str]],
    secondary: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for collection in (primary, secondary):
        for item in collection:
            path = str(item.get("path") or "")
            if not path or path in seen:
                continue
            merged.append(item)
            seen.add(path)
    return merged


def _restrict_targets_to_strategy_allowlist(
    *,
    selected_targets: list[dict[str, str]],
    strategy_selected_targets: list[dict[str, str]],
    strategy_allowlist: set[str],
    codebase_map: dict[str, Any],
) -> list[dict[str, str]]:
    allowed_selected = [
        target
        for target in selected_targets
        if str(target.get("path") or "") in strategy_allowlist
    ]
    if allowed_selected:
        return allowed_selected

    allowed_strategy_targets = [
        target
        for target in strategy_selected_targets
        if str(target.get("path") or "") in strategy_allowlist
    ]
    if allowed_strategy_targets:
        return allowed_strategy_targets

    candidate_sources = {
        str(item.get("path") or ""): item
        for item in (codebase_map.get("candidate_edit_targets") or [])
        if str(item.get("path") or "")
    }
    fallback_targets: list[dict[str, str]] = []
    for path in sorted(strategy_allowlist):
        candidate = candidate_sources.get(path)
        if candidate is None:
            continue
        fallback_targets.append(candidate)
    return fallback_targets


def _filter_seam_targets(targets: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    allowed: list[dict[str, str]] = []
    rejections: list[dict[str, str]] = []
    seen_rejections: set[tuple[str, str]] = set()
    for target in targets:
        path = str(target.get("path") or "").strip()
        rejection_reason = seam_target_rejection_reason(path)
        if rejection_reason is None:
            allowed.append(target)
            continue
        rejection_key = (path, rejection_reason)
        if rejection_key in seen_rejections:
            continue
        rejections.append({"path": path, "reason": rejection_reason})
        seen_rejections.add(rejection_key)
    return allowed, rejections


def _select_target_candidates_from_map(
    codebase_map: dict[str, Any],
    *,
    llm_codebase_interpretation: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    candidates_by_path = {
        str(item.get("path") or ""): item
        for item in (codebase_map.get("candidate_edit_targets") or [])
    }
    llm_ranked_candidates = list((llm_codebase_interpretation or {}).get("ranked_candidates") or [])
    if llm_ranked_candidates:
        selected: list[dict[str, str]] = []
        for item in llm_ranked_candidates:
            path = str(item.get("path") or "")
            candidate = candidates_by_path.get(path)
            if candidate is None:
                continue
            selected.append(
                {
                    **candidate,
                    "reason": str(item.get("reason") or candidate.get("reason") or ""),
                }
            )
        if selected:
            return selected

    selected_paths: list[str] = []

    auth_path = _pick_auth_candidate(codebase_map.get("auth_candidates") or [])
    if auth_path:
        selected_paths.append(auth_path)

    urlconf_path = _pick_urlconf_candidate(codebase_map.get("urlconf_candidates") or [])
    if urlconf_path:
        selected_paths.append(urlconf_path)

    frontend_path = _pick_frontend_candidate(codebase_map.get("frontend_component_candidates") or [])
    if frontend_path:
        selected_paths.append(frontend_path)

    entrypoint_path = _pick_entrypoint_candidate(candidates_by_path)
    if entrypoint_path:
        selected_paths.append(entrypoint_path)

    selected: list[dict[str, str]] = []
    for path in dict.fromkeys(selected_paths):
        candidate = candidates_by_path.get(path)
        if candidate is not None:
            selected.append(candidate)
    if selected:
        return selected

    fallback_candidates = list(candidates_by_path.values())
    fallback_candidates.sort(
        key=lambda item: (
            len(str(item.get("path") or "")),
            str(item.get("path") or ""),
        )
    )
    return fallback_candidates[:3]


def _pick_auth_candidate(auth_candidates: list[dict[str, object]]) -> str | None:
    if not auth_candidates:
        return None

    def score(item: dict[str, object]) -> tuple[int, int, str]:
        path = str(item.get("path") or "")
        functions = {str(name) for name in (item.get("functions") or [])}
        markers = {str(marker) for marker in (item.get("auth_markers") or [])}
        auth_score = 0
        if "login" in functions:
            auth_score += 5
        if "me" in functions:
            auth_score += 3
        if "session_token" in markers or "request.COOKIES" in markers:
            auth_score += 4
        if "/users/" in path:
            auth_score += 4
        if "/orders/" in path or "/products/" in path:
            auth_score -= 3
        return (-auth_score, len(path), path)

    return str(sorted(auth_candidates, key=score)[0]["path"])


def _pick_urlconf_candidate(urlconf_candidates: list[dict[str, object]]) -> str | None:
    if not urlconf_candidates:
        return None

    def score(item: dict[str, object]) -> tuple[int, int, str]:
        path = str(item.get("path") or "")
        include_targets = [str(target) for target in (item.get("include_targets") or [])]
        path_literals = [str(target) for target in (item.get("path_literals") or [])]
        route_score = 0
        if bool(item.get("has_urlpatterns")):
            route_score += 3
        if any("users" in target for target in include_targets):
            route_score += 4
        if any("login" in target or "me" in target for target in path_literals):
            route_score += 3
        if path.endswith("foodshop/urls.py") or path.endswith("config/urls.py") or path.endswith("project/urls.py"):
            route_score += 5
        if "/users/" in path:
            route_score += 2
        if "/orders/" in path or "/products/" in path:
            route_score -= 2
        return (-route_score, len(path), path)

    return str(sorted(urlconf_candidates, key=score)[0]["path"])


def _pick_frontend_candidate(frontend_candidates: list[dict[str, object]]) -> str | None:
    if not frontend_candidates:
        return None

    def score(item: dict[str, object]) -> tuple[int, int, str]:
        path = str(item.get("path") or "")
        markers = {str(marker) for marker in (item.get("markers") or [])}
        components = {str(component) for component in (item.get("components") or [])}
        mount_score = 0
        if "<BrowserRouter" in markers or "<Routes" in markers or "react-router-dom" in markers:
            mount_score += 4
        if "App" in components or path.lower().endswith("app.js") or path.lower().endswith("app.tsx"):
            mount_score += 3
        if "<Chatbot" in markers:
            mount_score += 2
        return (-mount_score, len(path), path)

    return str(sorted(frontend_candidates, key=score)[0]["path"])


def _pick_entrypoint_candidate(candidates_by_path: dict[str, dict[str, str]]) -> str | None:
    entrypoints = [
        path
        for path in candidates_by_path
        if path.lower().endswith(("main.py", "app.py"))
    ]
    if not entrypoints:
        return None
    return sorted(entrypoints, key=lambda path: (len(path), path))[0]


def write_unified_diff_draft(
    *,
    source_root: str | Path,
    generated_run_root: str | Path,
    proposal_path: str | Path,
    output_path: str | Path,
) -> Path:
    source = Path(source_root)
    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    patch_chunks: list[str] = []

    for target in proposal.get("target_files") or []:
        relative = str(target.get("path") or "")
        source_file = source / relative
        source_lines = _read_text_or_empty(source_file)
        insertion_hint = target.get("insertion_hint")
        if relative.endswith("views.py"):
            updated_lines = _build_python_stub_updated_lines(source_lines, insertion_hint=insertion_hint)
        elif relative.endswith("urls.py"):
            updated_lines = _build_url_registration_updated_lines(source_lines, insertion_hint=insertion_hint)
        elif relative.endswith("main.py"):
            updated_lines = _build_fastapi_registration_updated_lines(source_lines)
        elif relative.endswith("app.py"):
            updated_lines = _build_flask_registration_updated_lines(source_lines)
        elif _is_frontend_mount_target(relative):
            updated_lines = _build_frontend_mount_updated_lines(source_lines, relative, insertion_hint=insertion_hint)
        else:
            continue
        diff = difflib.unified_diff(
            source_lines,
            updated_lines,
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
        patch_chunks.append("".join(diff))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(patch_chunks), encoding="utf-8")
    return path


def _infer_intent(*, path: str, analysis: dict[str, Any], recommended_outputs: list[str]) -> str:
    lower = path.lower()
    if "views.py" in lower:
        return "extend backend auth/session handler for onboarding-compatible chat auth"
    if "urls.py" in lower:
        return "wire onboarding-related route entrypoint without touching the original source directly"
    if lower.endswith("main.py"):
        return "prepare FastAPI router registration draft for onboarding chat auth"
    if lower.endswith("app.py"):
        return "prepare Flask blueprint registration draft for onboarding chat auth"
    if lower.endswith(("app.js", "app.jsx", "app.tsx", "app.ts", ".vue")):
        return "prepare frontend chatbot mount draft for runtime-only integration review"
    if recommended_outputs:
        return f"support {recommended_outputs[0]} capability"
    return f"support auth style {((analysis.get('auth') or {}).get('auth_style') or 'unknown')}"


def _supporting_files(recommended_outputs: list[str]) -> list[str]:
    file_map = {
        "chat_auth": "files/backend/chat_auth.py",
        "order_adapter": "files/backend/order_adapter_client.py",
        "product_adapter": "files/backend/product_adapter_client.py",
        "frontend_patch": "patches/frontend_widget_mount.patch",
    }
    return [file_map[item] for item in recommended_outputs if item in file_map]


def _llm_patch_proposal_system_prompt() -> str:
    return (
        "You generate patch proposal JSON for onboarding integration.\n"
        "Return only JSON with keys: target_files, supporting_generated_files, recommended_outputs, analysis_summary.\n"
        "Select target_files conservatively from codebase_map.candidate_edit_targets only.\n"
        "Do not invent file paths.\n"
        "Prefer the smallest safe set of files needed for auth route, backend registration, and frontend mount.\n"
        "For frontend mount targets, include insertion_hint.mount_context and prefer outside_routes when a React app uses <Routes>.\n"
    )


def _validate_llm_patch_proposal_targets(
    *,
    llm_payload: PatchProposalPayload,
    codebase_map: dict[str, Any],
    recommended_outputs: list[str] | None = None,
) -> None:
    rejection = _build_llm_patch_proposal_target_rejection(
        llm_payload=llm_payload,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
    )
    if rejection is not None:
        raise ValueError(rejection["message"])


def _build_patch_proposal_file_samples(
    source_root: str | Path,
    codebase_map: dict[str, Any],
    *,
    limit: int = 4,
    max_chars: int = 500,
) -> list[dict[str, str]]:
    root = Path(source_root)
    samples: list[dict[str, str]] = []
    for item in (codebase_map.get("candidate_edit_targets") or [])[:limit]:
        relative = str(item.get("path") or "")
        path = root / relative
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        samples.append(
            {
                "path": relative,
                "content": content[:max_chars],
            }
        )
    return samples


def _llm_patch_system_prompt() -> str:
    return (
        "You generate only unified diff patches for onboarding integration.\n"
        "Return only a valid unified diff patch. Do not return JSON or markdown explanations.\n"
        "Prefer minimal edits to the target files in patch_proposal.target_files.\n"
        "Do not modify files outside the listed targets.\n"
        "Use evidence from analysis and codebase_map conservatively.\n"
        "If unsure, produce the smallest safe patch that preserves current behavior.\n"
        "The output must look like a unified diff starting with --- a/... and +++ b/...\n"
        "Every target file diff must include --- a/path, +++ b/path, and at least one @@ hunk header.\n"
        "Use hunk headers in the form @@ -old_start,old_count +new_start,new_count @@.\n"
        "Example hunk header: @@ -12,3 +12,7 @@.\n"
        "Do not emit standalone @@ lines or duplicate hunk markers.\n"
        "Do not return prose, bullets, comments, or code fences outside the unified diff.\n"
    )


def _normalize_llm_patch_content(content: str) -> tuple[str, str | None]:
    text = content.strip()
    recovery_reasons: list[str] = []
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
            recovery_reasons.append("patch_fences_removed")
    cleaned_lines: list[str] = []
    removed_redundant_hunk_marker = False
    for line in text.splitlines():
        if line.strip() == "@@":
            removed_redundant_hunk_marker = True
            continue
        cleaned_lines.append(line)
    if removed_redundant_hunk_marker:
        text = "\n".join(cleaned_lines)
        recovery_reasons.append("patch_redundant_hunk_marker_removed")
    text, salvage_recovery_reason = _salvage_valid_unified_diff_sections(text)
    if salvage_recovery_reason is not None:
        recovery_reasons.append(salvage_recovery_reason)
    if text and not text.endswith("\n"):
        text = f"{text}\n"
        recovery_reasons.append("patch_trailing_newline_added")
    recovery_reason = None
    for candidate in [
        "patch_fences_removed",
        "patch_redundant_hunk_marker_removed",
        "patch_invalid_trailing_file_section_removed",
        "patch_trailing_newline_added",
    ]:
        if candidate in recovery_reasons:
            recovery_reason = candidate
            break
    return text, recovery_reason


def _salvage_valid_unified_diff_sections(content: str) -> tuple[str, str | None]:
    sections = _split_unified_diff_sections(content)
    if len(sections) < 2:
        return content, None

    valid_sections: list[str] = []
    encountered_invalid_section = False
    for section in sections:
        if _is_valid_unified_diff_section(section):
            valid_sections.append(section)
            continue
        encountered_invalid_section = True
        break

    if valid_sections and encountered_invalid_section:
        return "\n".join(valid_sections).rstrip() + "\n", "patch_invalid_trailing_file_section_removed"
    return content, None


def _split_unified_diff_sections(content: str) -> list[str]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in content.splitlines():
        if line.startswith("--- a/"):
            if current:
                sections.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(section) for section in sections]


def _is_valid_unified_diff_section(section: str) -> bool:
    lines = section.splitlines()
    if len(lines) < 3:
        return False
    if not lines[0].startswith("--- a/") or not lines[1].startswith("+++ b/"):
        return False
    hunk_headers = [line for line in lines if line.startswith("@@")]
    if not hunk_headers or not all(_UNIFIED_DIFF_HUNK_HEADER_RE.match(line) for line in hunk_headers):
        return False
    return _section_hunks_match_declared_counts(lines[2:])


def _section_hunks_match_declared_counts(lines: list[str]) -> bool:
    index = 0
    saw_hunk = False
    while index < len(lines):
        line = lines[index]
        if not line.startswith("@@"):
            index += 1
            continue

        saw_hunk = True
        header_match = re.match(r"^@@ -(?P<old_start>\d+)(,(?P<old_count>\d+))? \+(?P<new_start>\d+)(,(?P<new_count>\d+))? @@", line)
        if header_match is None:
            return False

        old_count = int(header_match.group("old_count") or "1")
        new_count = int(header_match.group("new_count") or "1")
        old_seen = 0
        new_seen = 0
        index += 1

        while index < len(lines) and not lines[index].startswith("@@"):
            diff_line = lines[index]
            if diff_line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not diff_line:
                return False
            prefix = diff_line[0]
            if prefix == " ":
                old_seen += 1
                new_seen += 1
            elif prefix == "-":
                old_seen += 1
            elif prefix == "+":
                new_seen += 1
            else:
                return False
            index += 1

        if old_seen != old_count or new_seen != new_count:
            return False

    return saw_hunk


def _prepare_llm_patch_attempt(
    raw_content: str,
    *,
    patch_proposal: dict[str, Any],
) -> dict[str, Any]:
    normalized_content, recovery_reason = _normalize_llm_patch_content(raw_content)
    validation_error = _validate_llm_patch_content(normalized_content, patch_proposal=patch_proposal)
    return {
        "raw_response": raw_content,
        "normalized_response": normalized_content,
        "recovery_reason": recovery_reason,
        "validation_error": validation_error,
    }


def _llm_patch_retry_human_payload(
    *,
    source_root: str | Path,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    patch_proposal: dict[str, Any],
    previous_patch: str,
    validation_error: dict[str, str],
) -> str:
    return json.dumps(
        {
            "source_root": str(source_root),
            "analysis": analysis,
            "codebase_map": codebase_map,
            "patch_proposal": patch_proposal,
            "allowed_target_files": [str(item.get("path") or "") for item in (patch_proposal.get("target_files") or [])],
            "previous_patch": previous_patch,
            "validation_error": validation_error,
            "instruction": "Return only corrected unified diff text for the allowed target files.",
        },
        ensure_ascii=False,
        indent=2,
    )


def _llm_patch_proposal_retry_human_payload(
    *,
    source_root: str | Path,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    llm_codebase_interpretation: dict[str, Any] | None,
    recommended_outputs: list[str],
    fallback_payload: dict[str, Any],
    previous_patch_proposal: dict[str, Any],
    guardrail_rejection: dict[str, Any],
) -> str:
    strategy_allowlist = sorted(
        build_strategy_allowlist(
            integration_contract=codebase_map.get("integration_contract") or {},
            recommended_outputs=recommended_outputs,
            codebase_map=codebase_map,
        )
    )
    return json.dumps(
        {
            "source_root": str(source_root),
            "analysis": analysis,
            "codebase_map": codebase_map,
            "llm_codebase_interpretation": llm_codebase_interpretation,
            "file_samples": _build_patch_proposal_file_samples(source_root, codebase_map),
            "recommended_outputs": recommended_outputs,
            "fallback_patch_proposal": fallback_payload,
            "previous_patch_proposal": previous_patch_proposal,
            "guardrail_rejection": guardrail_rejection,
            "allowed_target_paths": strategy_allowlist,
            "allowed_mount_contexts": ["outside_routes", "root_fragment", "app_shell"],
            "instruction": "Return only corrected JSON patch proposal that avoids the rejected target and uses a valid source seam target. Do not place order-cs-widget inside <Routes>.",
        },
        ensure_ascii=False,
        indent=2,
    )


def _build_llm_patch_proposal_target_rejection(
    *,
    llm_payload: PatchProposalPayload,
    codebase_map: dict[str, Any],
    recommended_outputs: list[str] | None = None,
) -> dict[str, Any] | None:
    valid_paths = {
        str(item.get("path") or "")
        for item in (codebase_map.get("candidate_edit_targets") or [])
    }
    strategy_allowlist = build_strategy_allowlist(
        integration_contract=codebase_map.get("integration_contract") or {},
        recommended_outputs=recommended_outputs or [],
        codebase_map=codebase_map,
    )
    if not llm_payload.target_files:
        return {
            "path": "",
            "reason": "empty_target_files",
            "message": "target_files must not be empty",
        }
    if len(llm_payload.target_files) > 6:
        return {
            "path": llm_payload.target_files[0].path,
            "reason": "too_many_targets",
            "message": "target_files must remain conservative",
        }
    for target in llm_payload.target_files:
        if target.path not in valid_paths:
            return {
                "path": target.path,
                "reason": "invalid_target_path",
                "message": f"invalid target path: {target.path}",
            }
        seam_rejection = seam_target_rejection_reason(target.path)
        if seam_rejection is not None:
            return {
                "path": target.path,
                "reason": seam_rejection,
                "message": f"invalid seam target path: {target.path} ({seam_rejection})",
            }
        if strategy_allowlist and target.path not in strategy_allowlist:
            return {
                "path": target.path,
                "reason": "invalid_strategy_target_path",
                "message": f"invalid strategy target path: {target.path}",
            }
        mount_context = str((target.insertion_hint or {}).get("mount_context") or "").strip()
        if mount_context == "inside_routes":
            return {
                "path": target.path,
                "reason": "routes_child_violation",
                "message": f"invalid mount context for {target.path}: inside_routes would place order-cs-widget inside <Routes>",
            }
    return None


def _recover_patch_proposal_payload(
    payload: dict[str, Any],
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    fallback_payload: dict[str, Any],
) -> tuple[dict[str, Any], str] | None:
    if not isinstance(payload, dict):
        return None

    normalized = dict(payload)
    recovery_applied = False
    alias_map = {
        "targetFiles": "target_files",
        "supportingGeneratedFiles": "supporting_generated_files",
        "supportingFiles": "supporting_generated_files",
        "generatedFiles": "supporting_generated_files",
        "recommendedOutputs": "recommended_outputs",
        "outputs": "recommended_outputs",
        "analysisSummary": "analysis_summary",
        "summary": "analysis_summary",
    }
    for source_key, target_key in alias_map.items():
        if source_key in normalized and target_key not in normalized:
            normalized[target_key] = normalized.pop(source_key)
            recovery_applied = True

    target_files = normalized.get("target_files")
    if isinstance(target_files, dict):
        normalized["target_files"] = [target_files]
        recovery_applied = True
        target_files = normalized["target_files"]
    elif isinstance(target_files, str):
        normalized["target_files"] = [target_files]
        recovery_applied = True
        target_files = normalized["target_files"]

    candidates_by_path = {
        str(item.get("path") or ""): item
        for item in (codebase_map.get("candidate_edit_targets") or [])
        if str(item.get("path") or "")
    }
    if isinstance(target_files, list):
        normalized_targets: list[Any] = []
        target_recovered = False
        for item in target_files:
            if isinstance(item, str):
                candidate = candidates_by_path.get(item, {})
                normalized_targets.append(
                    {
                        "path": item,
                        "reason": str(candidate.get("reason") or ""),
                        "intent": _infer_intent(
                            path=item,
                            analysis=analysis,
                            recommended_outputs=recommended_outputs,
                        ),
                    }
                )
                target_recovered = True
                continue
            if isinstance(item, dict):
                path = str(item.get("path") or "")
                if not path:
                    normalized_targets.append(item)
                    continue
                candidate = candidates_by_path.get(path, {})
                normalized_item = dict(item)
                if not normalized_item.get("reason"):
                    normalized_item["reason"] = str(candidate.get("reason") or "")
                    target_recovered = True
                if not normalized_item.get("intent"):
                    normalized_item["intent"] = _infer_intent(
                        path=path,
                        analysis=analysis,
                        recommended_outputs=recommended_outputs,
                    )
                    target_recovered = True
                normalized_targets.append(normalized_item)
                continue
            normalized_targets.append(item)
        if target_recovered:
            normalized["target_files"] = normalized_targets
            recovery_applied = True

    supporting_generated_files = normalized.get("supporting_generated_files")
    if isinstance(supporting_generated_files, str):
        normalized["supporting_generated_files"] = [supporting_generated_files]
        recovery_applied = True
    elif not isinstance(supporting_generated_files, list):
        normalized["supporting_generated_files"] = list(fallback_payload.get("supporting_generated_files") or [])
        recovery_applied = True

    recommended_outputs = normalized.get("recommended_outputs")
    if isinstance(recommended_outputs, str):
        normalized["recommended_outputs"] = [recommended_outputs]
        recovery_applied = True
    elif not isinstance(recommended_outputs, list):
        normalized["recommended_outputs"] = list(fallback_payload.get("recommended_outputs") or [])
        recovery_applied = True

    analysis_summary = normalized.get("analysis_summary")
    if not isinstance(analysis_summary, dict):
        normalized["analysis_summary"] = dict(fallback_payload.get("analysis_summary") or {})
        recovery_applied = True

    if recovery_applied:
        return normalized, "patch_proposal_shape_normalized"
    return None


def _validate_llm_patch_content(
    content: str,
    *,
    patch_proposal: dict[str, Any],
) -> dict[str, str] | None:
    if not content.strip():
        return {"reason": "invalid_patch_format", "message": "empty patch content"}
    if not content.startswith("--- a/") or "\n+++ b/" not in content:
        return {"reason": "invalid_patch_format", "message": "missing unified diff file headers"}
    if "@@" not in content:
        return {"reason": "invalid_patch_format", "message": "missing unified diff hunk header"}
    invalid_hunks = [
        line
        for line in content.splitlines()
        if line.startswith("@@") and _UNIFIED_DIFF_HUNK_HEADER_RE.match(line) is None
    ]
    if invalid_hunks:
        return {
            "reason": "invalid_patch_format",
            "message": f"invalid unified diff hunk header: {invalid_hunks[0]}",
        }

    target_files = _extract_patch_targets_from_content(content)
    if not target_files:
        return {"reason": "invalid_patch_format", "message": "no target files found in unified diff"}

    valid_targets = {
        str(item.get("path") or "")
        for item in (patch_proposal.get("target_files") or [])
    }
    invalid_targets = [item for item in target_files if item not in valid_targets]
    if invalid_targets:
        return {
            "reason": "invalid_patch_targets",
            "message": f"patch references files outside proposal: {', '.join(invalid_targets)}",
        }

    return None


def _extract_patch_targets_from_content(content: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(r"^\+\+\+ b/(.+)$", content, re.MULTILINE)
    ]


def _build_llm_patch_placeholder(*, reason: str, message: str) -> str:
    return (
        f"# LLM patch rejected: {reason}\n"
        f"# {message}\n"
    )


def _patch_summary(path: Path) -> dict[str, Any]:
    content = _read_optional_text(path)
    target_files = []
    line_count = 0
    if content is not None:
        target_files = [
            line.removeprefix("+++ b/")
            for line in content.splitlines()
            if line.startswith("+++ b/")
        ]
        line_count = len(content.splitlines())
    return {
        "path": str(path),
        "exists": path.exists(),
        "target_files": target_files,
        "line_count": line_count,
    }


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _recommend_patch_source(
    *,
    deterministic_exists: bool,
    llm_exists: bool,
    same_content: bool,
    deterministic_targets: set[str],
    llm_targets: set[str],
    deterministic_passed: bool | None,
    llm_passed: bool | None,
) -> str:
    if deterministic_passed is False and llm_passed is True:
        return "llm"
    if deterministic_passed is True and llm_passed is False:
        return "deterministic"
    if deterministic_passed is True and llm_passed is True and same_content:
        return "deterministic"
    if deterministic_exists and not llm_exists:
        return "deterministic"
    if llm_exists and not deterministic_exists:
        return "llm"
    if same_content and deterministic_exists and llm_exists:
        return "deterministic"
    if deterministic_targets != llm_targets:
        return "manual_review"
    if deterministic_exists and llm_exists:
        return "manual_review"
    return "manual_review"


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_or_empty(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    return lines


def _build_python_stub_lines() -> list[str]:
    return [
        "\n",
        "def onboarding_chat_auth_token(request):\n",
        '    """Generated onboarding stub for runtime-only integration."""\n',
        "    return None\n",
    ]


def _build_python_stub_updated_lines(
    source_lines: list[str],
    *,
    insertion_hint: dict[str, Any] | None = None,
) -> list[str]:
    updated_lines = list(source_lines)
    stub_lines = _build_python_stub_lines()
    stub_signature = "def onboarding_chat_auth_token(request):\n"
    if stub_signature in updated_lines:
        return updated_lines

    hinted_index = _find_python_hint_insert_index(updated_lines, insertion_hint)
    if hinted_index is not None:
        updated_lines[hinted_index:hinted_index] = stub_lines
        return updated_lines

    insert_index = _find_auth_view_insert_index(updated_lines)
    if insert_index is None:
        return updated_lines + stub_lines

    updated_lines[insert_index:insert_index] = stub_lines
    return updated_lines


def _build_url_registration_stub_lines() -> list[str]:
    return [
        "\n",
        '# onboarding draft route registration\n',
        'path("api/chat/auth-token", onboarding_chat_auth_token),\n',
    ]


def _build_url_registration_updated_lines(
    source_lines: list[str],
    *,
    insertion_hint: dict[str, Any] | None = None,
) -> list[str]:
    updated_lines = _insert_import_after_existing_block(
        source_lines,
        "from users.views import onboarding_chat_auth_token\n",
    )
    route_line = '    path("api/chat/auth-token", onboarding_chat_auth_token),\n'
    if route_line in updated_lines:
        return updated_lines

    hinted_index = _find_simple_hint_insert_index(updated_lines, insertion_hint)
    if hinted_index is not None:
        updated_lines.insert(hinted_index, route_line)
        return updated_lines

    urlpatterns_index = _find_first_line_index(updated_lines, "urlpatterns")
    if urlpatterns_index is None:
        updated_lines.extend(_build_url_registration_stub_lines())
        return updated_lines

    closing_index = _find_list_closing_index(updated_lines, start_index=urlpatterns_index)
    if closing_index is None:
        updated_lines.extend(_build_url_registration_stub_lines())
        return updated_lines

    updated_lines.insert(closing_index, route_line)
    return updated_lines


def _build_fastapi_registration_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = _insert_import_after_existing_block(
        source_lines,
        "from backend.chat_auth import router as onboarding_chat_router\n",
    )
    include_line = "app.include_router(onboarding_chat_router)\n"
    if include_line in updated_lines:
        return updated_lines

    insert_index = _find_first_line_index(updated_lines, "app.include_router(")
    if insert_index is None:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", include_line])
        return updated_lines

    updated_lines.insert(insert_index, include_line)
    return updated_lines


def _build_flask_registration_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = _insert_import_after_existing_block(
        source_lines,
        "from backend.chat_auth import chat_auth_bp\n",
    )
    register_line = "app.register_blueprint(chat_auth_bp)\n"
    if register_line in updated_lines:
        return updated_lines

    insert_index = _find_first_line_index(updated_lines, "app.register_blueprint(")
    if insert_index is None:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", register_line])
        return updated_lines

    updated_lines.insert(insert_index, register_line)
    return updated_lines


def _is_frontend_mount_target(relative: str) -> bool:
    lower = relative.lower()
    return lower.endswith(("app.js", "app.jsx", "app.ts", "app.tsx", ".vue"))


def _build_frontend_mount_updated_lines(
    source_lines: list[str],
    relative: str,
    *,
    insertion_hint: dict[str, Any] | None = None,
) -> list[str]:
    updated_lines = list(source_lines)
    lower = relative.lower()
    if lower.endswith(".vue"):
        return _build_vue_mount_updated_lines(updated_lines)
    return _build_react_mount_updated_lines(updated_lines, insertion_hint=insertion_hint)


def _build_react_mount_updated_lines(
    source_lines: list[str],
    *,
    insertion_hint: dict[str, Any] | None = None,
) -> list[str]:
    updated_lines = list(source_lines)
    if '__ORDER_CS_WIDGET_HOST_CONTRACT__' not in "".join(updated_lines):
        updated_lines = _insert_lines_after_existing_block(
            updated_lines,
            _build_shared_widget_bootstrap_lines(),
        )
    widget_line = "      <order-cs-widget />\n"
    if widget_line in updated_lines:
        return updated_lines

    mount_context = str((insertion_hint or {}).get("mount_context") or "").strip()
    if mount_context == "outside_routes":
        outside_routes_index = _find_outside_routes_insert_index(updated_lines, insertion_hint)
        if outside_routes_index is not None:
            updated_lines.insert(outside_routes_index, widget_line)
            return updated_lines

    hinted_index = _find_simple_hint_insert_index(updated_lines, insertion_hint)
    if hinted_index is not None:
        updated_lines.insert(hinted_index, widget_line)
        return updated_lines

    insert_index = _find_react_mount_insert_index(updated_lines)
    if insert_index is None:
        fallback_line = "  <order-cs-widget />\n"
        if fallback_line not in updated_lines:
            if updated_lines and not updated_lines[-1].endswith("\n"):
                updated_lines[-1] = f"{updated_lines[-1]}\n"
            updated_lines.extend(["\n", fallback_line])
        return updated_lines

    updated_lines.insert(insert_index, widget_line)
    return updated_lines


def _build_vue_mount_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    widget_line = "  <order-cs-widget />\n"
    if '__ORDER_CS_WIDGET_HOST_CONTRACT__' not in "".join(updated_lines):
        script_close = next((index for index, line in enumerate(updated_lines) if "</script>" in line), None)
        insertion = list(_build_shared_widget_bootstrap_lines())
        if script_close is not None:
            if script_close > 0 and updated_lines[script_close - 1].strip():
                insertion.insert(0, "\n")
            updated_lines[script_close:script_close] = insertion
        else:
            updated_lines.extend(["\n", "<script setup>\n", *insertion, "</script>\n"])
    if widget_line not in updated_lines:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", "<template>\n", widget_line, "</template>\n"])
    return updated_lines


def _build_shared_widget_bootstrap_lines() -> list[str]:
    contract = build_frontend_mount_contract()
    return [
        "const ORDER_CS_WIDGET_HOST_CONTRACT = {\n",
        f'  chatbotServerBaseUrl: "{contract["chatbotServerBaseUrl"]}",\n',
        f'  authBootstrapPath: "{contract["authBootstrapPath"]}",\n',
        f'  widgetBundlePath: "{contract["widgetBundlePath"]}",\n',
        f'  widgetElementTag: "{contract["widgetElementTag"]}",\n',
        f'  mountMode: "{contract["mountMode"]}",\n',
        "};\n",
        "\n",
        'if (typeof globalThis === "object") {\n',
        '  globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;\n',
        "}\n",
        "\n",
        'if (typeof document !== "undefined" && !document.querySelector(\'script[data-order-cs-widget-bundle="true"]\')) {\n',
        '  const orderCsWidgetScript = document.createElement("script");\n',
        "  orderCsWidgetScript.src = `${ORDER_CS_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl}${ORDER_CS_WIDGET_HOST_CONTRACT.widgetBundlePath}`;\n",
        "  orderCsWidgetScript.async = true;\n",
        '  orderCsWidgetScript.dataset.orderCsWidgetBundle = "true";\n',
        "  document.head.appendChild(orderCsWidgetScript);\n",
        "}\n",
        "\n",
    ]


def _insert_lines_after_existing_block(source_lines: list[str], insertion_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    if not insertion_lines:
        return updated_lines

    insert_index = 0
    for index, line in enumerate(updated_lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_index = index + 1
            continue
        if stripped == "":
            if insert_index:
                insert_index = index + 1
            continue
        break

    updated_lines[insert_index:insert_index] = insertion_lines
    return updated_lines


def _insert_import_after_existing_block(source_lines: list[str], import_line: str) -> list[str]:
    return _insert_lines_after_existing_block(source_lines, [import_line])


def _find_first_line_index(lines: list[str], marker: str) -> int | None:
    for index, line in enumerate(lines):
        if marker in line:
            return index
    return None


def _find_simple_hint_insert_index(lines: list[str], insertion_hint: dict[str, Any] | None) -> int | None:
    if not insertion_hint:
        return None
    anchor_text = str(insertion_hint.get("anchor_text") or "").strip()
    if not anchor_text:
        return None
    position = str(insertion_hint.get("position") or "after")
    for index, line in enumerate(lines):
        if line.strip() == anchor_text:
            return index if position == "before" else index + 1
    return None


def _find_python_hint_insert_index(lines: list[str], insertion_hint: dict[str, Any] | None) -> int | None:
    anchor_index = _find_hint_anchor_index(lines, insertion_hint)
    if anchor_index is None:
        return None
    for index in range(anchor_index + 1, len(lines)):
        if lines[index].startswith("def "):
            if index > 0 and lines[index - 1].strip() == "":
                return index - 1
            return index
    return len(lines)


def _find_hint_anchor_index(lines: list[str], insertion_hint: dict[str, Any] | None) -> int | None:
    if not insertion_hint:
        return None
    anchor_text = str(insertion_hint.get("anchor_text") or "").strip()
    if not anchor_text:
        return None
    for index, line in enumerate(lines):
        if line.strip() == anchor_text:
            return index
    return None


def _find_list_closing_index(lines: list[str], *, start_index: int) -> int | None:
    bracket_depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        bracket_depth += line.count("[")
        if line.count("["):
            seen_open = True
        bracket_depth -= line.count("]")
        if seen_open and bracket_depth <= 0 and "]" in line:
            return index
    return None


def _find_react_mount_insert_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in {"</BrowserRouter>", "</Routes>", "</main>", "</div>"}:
            return index
    return None


def _find_outside_routes_insert_index(
    lines: list[str],
    insertion_hint: dict[str, Any] | None,
) -> int | None:
    anchor_index = _find_hint_anchor_index(lines, insertion_hint)
    if anchor_index is not None:
        position = str((insertion_hint or {}).get("position") or "after")
        return anchor_index if position == "before" else anchor_index + 1

    browser_router_close_index = _find_first_line_index(lines, "</BrowserRouter>")
    if browser_router_close_index is not None:
        return browser_router_close_index

    routes_close_index = _find_first_line_index(lines, "</Routes>")
    if routes_close_index is not None:
        return routes_close_index + 1

    return _find_react_mount_insert_index(lines)


def _find_auth_view_insert_index(lines: list[str]) -> int | None:
    auth_function_names = {"login", "me", "logout", "signup", "signin", "session", "refresh"}
    candidate_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("def "):
            continue

        function_name = stripped[4:].split("(", 1)[0].strip()
        if function_name not in auth_function_names:
            continue

        candidate_index = _find_function_end_index(lines, start_index=index)

    return candidate_index


def _find_function_end_index(lines: list[str], *, start_index: int) -> int:
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("def ") or stripped.startswith("class "):
            return index
    return len(lines)
