import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.failure_classifier import build_failure_signature, classify_onboarding_failure


def test_build_failure_signature_normalizes_routes_child_violation():
    assert build_failure_signature(
        classification="frontend_mount_violation",
        detail="routes child violation",
    ) == "frontend_mount_violation:routes_child_violation"


def test_build_failure_signature_normalizes_llm_payload_shape_errors():
    assert build_failure_signature(
        classification="codebase_interpretation",
        detail=(
            "1 validation error for CodebaseInterpretationPayload\n"
            "structure_summary\n"
            "  Input should be a valid string"
        ),
    ) == "codebase_interpretation:invalid_llm_payload.structure_summary_type"


def test_classify_onboarding_failure_uses_runtime_completion_prefix():
    payload = classify_onboarding_failure(
        failure_signature="frontend_import_resolution_failed:shared_chatbot_widget",
        failed_results=[],
    )

    assert payload["classification"] == "frontend_import_resolution_failed"
    assert payload["repairable"] is True
