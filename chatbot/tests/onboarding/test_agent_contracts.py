import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import (
    AgentMessage,
    ApprovalType,
    RunEvent,
    RunState,
)


def test_run_state_contains_expected_values():
    assert RunState.QUEUED.value == "queued"
    assert RunState.ANALYZING.value == "analyzing"
    assert RunState.AWAITING_APPLY_APPROVAL.value == "awaiting_apply_approval"
    assert RunState.HUMAN_REVIEW_REQUIRED.value == "human_review_required"
    assert RunState.COMPLETED.value == "completed"


def test_approval_type_contains_expected_values():
    assert ApprovalType.ANALYSIS.value == "analysis"
    assert ApprovalType.APPLY.value == "apply"
    assert ApprovalType.EXPORT.value == "export"


def test_agent_message_requires_structured_fields():
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session['user_id'] is written in login route"],
        confidence=0.92,
        risk="medium",
        next_action="pass auth capability to planner",
        blocking_issue="none",
    )

    assert message.role == "Analyzer"
    assert message.confidence == 0.92


def test_agent_message_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        AgentMessage(
            role="Analyzer",
            claim="Detected session auth",
            evidence=["session['user_id'] is written in login route"],
            confidence=1.4,
            risk="medium",
            next_action="pass auth capability to planner",
            blocking_issue="none",
        )


def test_run_event_contains_required_fields():
    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"message": "done"},
        created_at="2026-03-15T23:00:00+09:00",
    )

    assert event.event_type == "analysis.completed"
    assert event.state == RunState.ANALYZING
    assert event.payload["message"] == "done"
