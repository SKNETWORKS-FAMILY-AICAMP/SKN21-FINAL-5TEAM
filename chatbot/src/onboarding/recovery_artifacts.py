from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .smoke_contract import SmokeRecoveryPayload, SmokeTestPlan, SmokeTestStep


def build_recovered_smoke_plan(
    *,
    smoke_steps: list[dict[str, Any]],
    recovery_payload: SmokeRecoveryPayload | dict[str, Any],
) -> dict[str, Any]:
    normalized_payload = (
        recovery_payload
        if isinstance(recovery_payload, SmokeRecoveryPayload)
        else SmokeRecoveryPayload.model_validate(_filter_smoke_recovery_payload(recovery_payload))
    )
    plan = SmokeTestPlan.model_validate({"steps": smoke_steps})
    recovered_steps = [
        _apply_recovery_to_step(step=step, recovery_payload=normalized_payload).model_dump()
        for step in plan.steps
    ]
    return {
        "classification": normalized_payload.classification,
        "should_retry": normalized_payload.should_retry,
        "steps": recovered_steps,
    }


def write_recovered_smoke_plan(
    *,
    run_root: str | Path,
    smoke_steps: list[dict[str, Any]],
    recovery_payload: SmokeRecoveryPayload | dict[str, Any],
) -> Path:
    root = Path(run_root)
    recovered_plan = build_recovered_smoke_plan(
        smoke_steps=smoke_steps,
        recovery_payload=recovery_payload,
    )
    output_path = root / "reports" / "recovered-smoke-plan.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(recovered_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _apply_recovery_to_step(
    *,
    step: SmokeTestStep,
    recovery_payload: SmokeRecoveryPayload,
) -> SmokeTestStep:
    step_payload = step.model_dump()
    for update in recovery_payload.proposed_probe_updates:
        if update.step_id != step.id:
            continue
        for key, value in update.merge.items():
            current = step_payload.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged = dict(current)
                merged.update(value)
                step_payload[key] = merged
            else:
                step_payload[key] = value

    for override in recovery_payload.proposed_schema_overrides:
        if override.step_id != step.id:
            continue
        if override.expects is not None:
            step_payload["expects"] = override.expects.model_dump()
        if override.exports:
            merged_exports = dict(step_payload.get("exports") or {})
            merged_exports.update(override.exports)
            step_payload["exports"] = merged_exports

    return SmokeTestStep.model_validate(step_payload)


def _filter_smoke_recovery_payload(payload: SmokeRecoveryPayload | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, SmokeRecoveryPayload):
        return payload.model_dump(mode="json")
    allowed_keys = set(SmokeRecoveryPayload.model_fields)
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if key in allowed_keys
    }
