from __future__ import annotations

from typing import Any


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

    if "missing chat auth import target" in backend_errors:
        return {
            "classification": "missing_import_target",
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
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_frontend_mount",
                    "reason": "routes child violation",
                }
            ],
        }
    if "widget path outside frontend/src" in frontend_errors:
        return {
            "classification": "frontend_mount_violation",
            "repairable": True,
            "repair_actions": [
                {
                    "action": "relocate_widget_into_src",
                    "target_path": "frontend/src/chatbot/SharedChatbotWidget.jsx",
                }
            ],
        }

    normalized_signature = str(failure_signature or "").strip()
    if normalized_signature.startswith("response_schema_mismatch"):
        return {
            "classification": "response_schema_mismatch",
            "repairable": True,
            "repair_actions": [],
        }
    if normalized_signature.startswith("probe_contract_mismatch"):
        return {
            "classification": "probe_contract_mismatch",
            "repairable": True,
            "repair_actions": [],
        }
    if normalized_signature.startswith("missing_smoke_script"):
        return {
            "classification": "missing_smoke_script",
            "repairable": False,
            "repair_actions": [],
        }

    if any("Smoke script not found" in str(result.get("stderr") or "") for result in failed_results):
        return {
            "classification": "missing_smoke_script",
            "repairable": False,
            "repair_actions": [],
        }
    if any(bool(result.get("timed_out")) or int(result.get("returncode") or 0) == 124 for result in failed_results):
        return {
            "classification": "transient_timeout",
            "repairable": True,
            "repair_actions": [],
        }
    return {
        "classification": "transient_runtime_failure",
        "repairable": True,
        "repair_actions": [],
    }
