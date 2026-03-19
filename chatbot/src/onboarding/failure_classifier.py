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
    normalized_signature = str(failure_signature or "").strip()

    runtime_completion_classes = {
        "frontend_import_resolution_failed": {
            "repairable": True,
            "repair_actions": [
                {
                    "action": "repair_shared_widget_import",
                    "target_path": "frontend/src/chatbot/SharedChatbotWidget.jsx",
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
            "repairable": payload["repairable"],
            "repair_actions": payload["repair_actions"],
        }

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
