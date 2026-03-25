from __future__ import annotations

import re
from typing import Any


def build_failure_signature(*, classification: str, detail: str | None = None) -> str:
    normalized_classification = _normalize_failure_token(classification)
    normalized_detail = _normalize_failure_detail(detail)
    if normalized_detail:
        return f"{normalized_classification}:{normalized_detail}"
    return normalized_classification


def classify_onboarding_failure(
    *,
    failure_signature: str,
    failed_results: list[dict[str, Any]] | None = None,
    backend_evaluation: dict[str, Any] | None = None,
    frontend_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failed_results = list(failed_results or [])
    backend_evaluation = backend_evaluation or {}
    frontend_evaluation = frontend_evaluation or {}

    backend_route_wiring = backend_evaluation.get("route_wiring") or {}
    backend_errors = [str(item) for item in backend_route_wiring.get("validation_errors") or []]
    frontend_artifact = frontend_evaluation.get("frontend_artifact") or {}
    frontend_errors = [str(item) for item in frontend_artifact.get("validation_errors") or []]
    normalized_signature = str(failure_signature or "").strip()

    runtime_completion_classes = {
        "frontend_import_resolution_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount_bundle",
                    "target_path": "frontend/src",
                }
            ],
        },
        "frontend_dev_server_boot_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_dev_bootstrap",
                    "target_path": "frontend/package.json",
                }
            ],
        },
        "frontend_readiness_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_dev_bootstrap",
                    "target_path": "frontend/package.json",
                }
            ],
        },
        "backend_server_boot_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_backend_entrypoint",
                    "target_path": "backend",
                }
            ],
        },
        "backend_import_resolution_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_backend_entrypoint",
                    "target_path": "backend",
                }
            ],
        },
        "django_urlconf_import_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_backend_entrypoint",
                    "target_path": "backend",
                }
            ],
        },
        "backend_readiness_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_backend_entrypoint",
                    "target_path": "backend",
                }
            ],
        },
        "chatbot_mount_missing": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount_target",
                    "target_path": "frontend/src",
                }
            ],
        },
        "chatbot_status_not_rendered": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount_target",
                    "target_path": "frontend/src",
                }
            ],
        },
        "mount_probe_environment_unsupported": {
            "repairable": False,
            "repair_actions": [],
        },
    }
    signature_head, _, _ = normalized_signature.partition(":")
    if signature_head in runtime_completion_classes:
        payload = runtime_completion_classes[signature_head]
        return {
            "classification": signature_head,
            "failure_signature": build_failure_signature(
                classification=signature_head,
                detail=normalized_signature.partition(":")[2] or None,
            ),
            "repairable": payload["repairable"],
            "repair_actions": payload["repair_actions"],
        }

    if "missing chat auth import target" in backend_errors:
        return {
            "classification": "missing_import_target",
            "failure_signature": build_failure_signature(
                classification="missing_import_target",
                detail="missing_chat_auth_import_target",
            ),
            "repairable": True,
            "repair_actions": [
                {
                    "action": "create_chat_auth_module",
                    "target_path": "backend/chat_auth.py",
                    "framework": str(backend_evaluation.get("framework") or "unknown"),
                }
            ],
        }
    if "route target outside detected registration point" in backend_errors:
        return {
            "classification": "route_wiring_failure",
            "failure_signature": build_failure_signature(
                classification="route_wiring_failure",
                detail="route_target_outside_detected_registration_point",
            ),
            "repairable": True,
            "repair_actions": [
                {
                    "action": "move_chat_auth_route",
                    "target_path": str(backend_route_wiring.get("detected_registration_point") or ""),
                }
            ],
        }
    if "routes child violation" in frontend_errors:
        return {
            "classification": "frontend_mount_violation",
            "failure_signature": build_failure_signature(
                classification="frontend_mount_violation",
                detail="routes child violation",
            ),
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount",
                    "reason": "routes child violation",
                }
            ],
        }
    if any(
        error in frontend_errors
        for error in {
            "mount missing order-cs-widget bundle bootstrap",
            "mount missing auth bootstrap contract",
            "mount missing order-cs-widget usage",
            "widget path outside frontend/src",
        }
    ):
        return {
            "classification": "frontend_mount_violation",
            "failure_signature": build_failure_signature(
                classification="frontend_mount_violation",
                detail="mount missing widget contract",
            ),
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount_target",
                    "target_path": "frontend/src",
                }
            ],
        }

    if normalized_signature.startswith("response_schema_mismatch"):
        return {
            "classification": "response_schema_mismatch",
            "failure_signature": build_failure_signature(
                classification="response_schema_mismatch",
                detail=normalized_signature.partition(":")[2] or None,
            ),
            "repairable": True,
            "repair_actions": [],
        }
    if normalized_signature.startswith("probe_contract_mismatch"):
        return {
            "classification": "probe_contract_mismatch",
            "failure_signature": build_failure_signature(
                classification="probe_contract_mismatch",
                detail=normalized_signature.partition(":")[2] or None,
            ),
            "repairable": True,
            "repair_actions": [],
        }
    if normalized_signature.startswith("missing_smoke_script"):
        return {
            "classification": "missing_smoke_script",
            "failure_signature": build_failure_signature(
                classification="missing_smoke_script",
                detail=normalized_signature.partition(":")[2] or None,
            ),
            "repairable": False,
            "repair_actions": [],
        }

    if any("Smoke script not found" in str(result.get("stderr") or "") for result in failed_results):
        return {
            "classification": "missing_smoke_script",
            "failure_signature": build_failure_signature(
                classification="missing_smoke_script",
                detail="script_not_found",
            ),
            "repairable": False,
            "repair_actions": [],
        }
    if any(bool(result.get("timed_out")) or int(result.get("returncode") or 0) == 124 for result in failed_results):
        return {
            "classification": "transient_timeout",
            "failure_signature": build_failure_signature(
                classification="transient_timeout",
                detail="timeout",
            ),
            "repairable": True,
            "repair_actions": [],
        }
    return {
        "classification": "transient_runtime_failure",
        "failure_signature": build_failure_signature(
            classification="transient_runtime_failure",
            detail=normalized_signature or None,
        ),
        "repairable": True,
        "repair_actions": [],
    }


def _normalize_failure_detail(detail: str | None) -> str:
    if not detail:
        return ""
    normalized = str(detail).strip().lower()
    if "structure_summary" in normalized and "input should be a valid string" in normalized:
        return "invalid_llm_payload.structure_summary_type"
    known_details = {
        "invalid_llm_payload.structure_summary type": "invalid_llm_payload.structure_summary_type",
        "routes child violation": "routes_child_violation",
        "mount missing widget contract": "mount_missing_widget_contract",
        "mount missing order-cs-widget bundle bootstrap": "mount_missing_widget_contract",
        "mount missing auth bootstrap contract": "mount_missing_widget_contract",
        "mount missing order-cs-widget usage": "mount_missing_widget_contract",
        "mount candidate unavailable": "mount_missing_widget_contract",
    }
    if normalized in known_details:
        return known_details[normalized]
    normalized = normalized.replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9._|]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_.")


def _normalize_failure_token(value: str | None) -> str:
    normalized = _normalize_failure_detail(value)
    return normalized or "unknown_failure"
