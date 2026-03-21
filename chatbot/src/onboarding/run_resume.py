from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


STAGE_ORDER = ["analysis", "generation", "validation", "export"]


@dataclass(frozen=True)
class ResumeCheckpoint:
    run_root: str
    last_completed_stage: str | None
    failed_stage: str | None
    resume_from_stage: str | None
    reason: str
    latest_failure_signature: str | None = None
    failure_count_for_signature: int | None = None
    repair_history_path: str | None = None


def analyze_run_checkpoint(run_root: str | Path) -> ResumeCheckpoint:
    root = Path(run_root)
    reports = root / "reports"

    has_analysis = (root / "manifest.json").exists() and (reports / "codebase-map.json").exists()
    has_generation = has_analysis and (reports / "patch-proposal.json").exists() and (root / "patches" / "proposed.patch").exists()

    merge_payload = _read_json(reports / "merge-simulation.json")
    smoke_payload = _read_json(reports / "smoke-summary.json")
    frontend_build_payload = _read_json(reports / "frontend-build-validation.json")
    export_payload = _read_json(reports / "export-metadata.json")

    last_completed_stage: str | None = None
    failed_stage: str | None = None
    reason = "no checkpoint artifacts found"

    if has_analysis:
        last_completed_stage = "analysis"
        reason = "analysis artifacts present"
    if has_generation:
        last_completed_stage = "generation"
        reason = "generation artifacts present"

    validation_passed = _validation_passed(root)
    if validation_passed:
        last_completed_stage = "validation"
        reason = "validation artifacts passed"
    elif has_generation:
        merge_passed = merge_payload.get("passed") is True if isinstance(merge_payload, dict) else False
        smoke_passed = smoke_payload.get("passed") is True if isinstance(smoke_payload, dict) else False
        frontend_failure = str(frontend_build_payload.get("bootstrap_failure_reason") or "").strip() if isinstance(frontend_build_payload, dict) else ""
        if merge_passed and (frontend_failure or (isinstance(smoke_payload, dict) and smoke_passed is False)):
            failed_stage = "validation"
            reason = frontend_failure or "smoke validation failed"
        elif isinstance(merge_payload, dict) and merge_payload.get("passed") is False:
            failed_stage = "validation"
            reason = "merge simulation failed"

    if export_payload:
        last_completed_stage = "export"
        failed_stage = None
        reason = "export metadata present"

    resume_from_stage = _next_stage(last_completed_stage) if failed_stage is None else failed_stage
    if last_completed_stage == "export":
        resume_from_stage = None

    repair_history = _read_json(reports / "repair-history.json")

    return ResumeCheckpoint(
        run_root=str(root),
        last_completed_stage=last_completed_stage,
        failed_stage=failed_stage,
        resume_from_stage=resume_from_stage,
        reason=reason,
        latest_failure_signature=str(repair_history.get("failure_signature") or "") or None,
        failure_count_for_signature=_coerce_int(repair_history.get("failure_count_for_signature")),
        repair_history_path=str(reports / "repair-history.json") if repair_history else None,
    )


def _validation_passed(run_root: Path) -> bool:
    reports = run_root / "reports"
    smoke_payload = _read_json(reports / "smoke-summary.json")
    if not isinstance(smoke_payload, dict) or smoke_payload.get("passed") is not True:
        return False
    return (reports / "backend-evaluation.json").exists() and (reports / "frontend-evaluation.json").exists()


def _next_stage(stage: str | None) -> str | None:
    if stage is None:
        return "analysis"
    try:
        index = STAGE_ORDER.index(stage)
    except ValueError:
        return None
    next_index = index + 1
    if next_index >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[next_index]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
