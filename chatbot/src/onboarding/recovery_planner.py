from __future__ import annotations

from typing import Any

from .failure_classifier import classify_onboarding_failure


_RECOVERABLE_CLASSIFICATIONS = {
    "missing_import_target",
    "route_wiring_failure",
    "frontend_mount_violation",
    "frontend_import_resolution_failed",
    "frontend_dev_server_boot_failed",
    "frontend_readiness_failed",
    "backend_server_boot_failed",
    "backend_import_resolution_failed",
    "django_urlconf_import_failed",
    "backend_readiness_failed",
    "chatbot_mount_missing",
    "chatbot_status_not_rendered",
    "response_schema_mismatch",
    "probe_contract_mismatch",
    "transient_runtime_failure",
    "transient_timeout",
}

_SITE_LOCAL_CLASSIFICATIONS = {
    "response_schema_mismatch",
    "probe_contract_mismatch",
}


def classify_failure_signature(signature: str) -> str:
    head, _, _ = (signature or "").partition(":")
    normalized = head.strip() or "unknown_failure"
    return normalized


def is_site_local_failure_signature(signature: str) -> bool:
    return classify_failure_signature(signature) in _SITE_LOCAL_CLASSIFICATIONS


def build_recovery_plan(context: dict[str, Any]) -> dict[str, Any]:
    failed_results = list(context.get("failed_results") or [])
    classification_payload = classify_onboarding_failure(
        failure_signature=str(context.get("failure_signature") or ""),
        failed_results=failed_results,
        backend_evaluation=context.get("backend_evaluation") or {},
        frontend_evaluation=context.get("frontend_evaluation") or {},
    )
    classification = str(classification_payload.get("classification") or "")
    retry_count = int(context.get("retry_count") or 0)
    retry_budget = int(context.get("retry_budget") or 0)
    repair_actions = list(classification_payload.get("repair_actions") or [])
    should_retry = (
        classification in _RECOVERABLE_CLASSIFICATIONS
        and bool(classification_payload.get("repairable", False))
        and retry_count < retry_budget
    )
    if not should_retry:
        return {
            "classification": classification,
            "should_retry": False,
            "proposed_probe_updates": [],
            "proposed_schema_overrides": [],
            "repair_actions": repair_actions,
        }

    failed_step_ids = [
        str(result.get("step_id") or result.get("step") or "").strip()
        for result in failed_results
        if str(result.get("step_id") or result.get("step") or "").strip()
    ]

    proposed_probe_updates: list[dict[str, Any]] = []
    proposed_schema_overrides: list[dict[str, Any]] = []

    for step_id in failed_step_ids:
        if classification == "response_schema_mismatch":
            proposed_schema_overrides.append(
                {
                    "step_id": step_id,
                    "exports": {
                        "chat_auth.access_token": "body.access_token.token",
                    },
                }
            )
        elif classification == "probe_contract_mismatch":
            proposed_probe_updates.append(
                {
                    "step_id": step_id,
                    "merge": {
                        "response": {
                            "body_path": "$.items",
                        }
                    },
                }
            )

    return {
        "classification": classification,
        "should_retry": should_retry,
        "proposed_probe_updates": proposed_probe_updates,
        "proposed_schema_overrides": proposed_schema_overrides,
        "repair_actions": repair_actions,
    }


def _normalize_recovery_classification(*, signature: str, failed_results: list[dict[str, Any]]) -> str:
    classification = classify_failure_signature(signature)
    if classification in {
        "response_schema_mismatch",
        "probe_contract_mismatch",
        "missing_smoke_script",
    }:
        return classification
    if any("Smoke script not found" in str(result.get("stderr") or "") for result in failed_results):
        return "missing_smoke_script"
    if any(bool(result.get("timed_out")) or int(result.get("returncode") or 0) == 124 for result in failed_results):
        return "transient_timeout"
    return "transient_runtime_failure"
