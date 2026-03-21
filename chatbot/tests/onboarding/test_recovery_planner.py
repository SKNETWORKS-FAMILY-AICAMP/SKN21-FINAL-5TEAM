import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def _failure_result(*, step_id: str = "chat-auth-token", stderr: str = "expected string but got object") -> dict:
    return {
        "step": step_id,
        "step_id": step_id,
        "required": True,
        "category": "auth",
        "timed_out": False,
        "returncode": 1,
        "stdout": "",
        "stderr": stderr,
        "response": {
            "status": 200,
            "headers": {},
            "body": '{"access_token": {"token": "nested"}}',
        },
        "exports": {},
    }


def test_recovery_payload_contract_is_locked():
    from chatbot.src.onboarding.recovery_planner import build_recovery_plan

    payload = build_recovery_plan(
        {
            "failure_signature": "response_schema_mismatch:chat-auth-token",
            "retry_count": 0,
            "retry_budget": 2,
            "failed_results": [_failure_result()],
        }
    )

    assert payload["classification"] == "response_schema_mismatch"
    assert payload["should_retry"] is True
    assert set(payload) == {
        "classification",
        "should_retry",
        "proposed_probe_updates",
        "proposed_schema_overrides",
        "repair_actions",
    }


def test_non_recoverable_failure_returns_no_retry():
    from chatbot.src.onboarding.recovery_planner import build_recovery_plan

    payload = build_recovery_plan(
        {
            "failure_signature": "missing_smoke_script:login",
            "retry_count": 0,
            "retry_budget": 2,
            "failed_results": [_failure_result(step_id="login", stderr="Smoke script not found")],
        }
    )

    assert payload["classification"] == "missing_smoke_script"
    assert payload["should_retry"] is False
    assert payload["proposed_probe_updates"] == []
    assert payload["proposed_schema_overrides"] == []
    assert payload["repair_actions"] == []


@pytest.mark.parametrize(
    ("signature", "expected_classification"),
    [
        ("response_schema_mismatch:chat-auth-token", "response_schema_mismatch"),
        ("probe_contract_mismatch:product-api", "probe_contract_mismatch"),
    ],
)
def test_known_failure_signatures_map_to_recovery_classification(signature: str, expected_classification: str):
    from chatbot.src.onboarding.recovery_planner import classify_failure_signature

    assert classify_failure_signature(signature) == expected_classification


def test_recovery_plan_proposes_patch_repair_for_missing_import_target():
    from chatbot.src.onboarding.recovery_planner import build_recovery_plan

    payload = build_recovery_plan(
        {
            "failure_signature": "runtime_validation_failure",
            "retry_count": 0,
            "retry_budget": 2,
            "failed_results": [],
            "backend_evaluation": {
                "framework": "django",
                "route_wiring": {
                    "validation_errors": ["missing chat auth import target"],
                },
            },
        }
    )

    assert payload["classification"] == "missing_import_target"
    assert payload["should_retry"] is True
    assert payload["repair_actions"] == [
        {
            "action": "create_chat_auth_module",
            "target_path": "backend/chat_auth.py",
            "framework": "django",
        }
    ]


def test_response_schema_mismatch_is_treated_as_site_local_signature():
    from chatbot.src.onboarding.recovery_planner import is_site_local_failure_signature

    assert is_site_local_failure_signature("response_schema_mismatch:chat-auth-token") is True
    assert is_site_local_failure_signature("frontend_target_detection:build_artifact_selected") is False
