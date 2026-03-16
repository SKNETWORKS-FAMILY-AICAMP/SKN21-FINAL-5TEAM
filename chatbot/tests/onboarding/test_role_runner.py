import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import AgentMessage, RunEvent, RunState
from chatbot.src.onboarding.role_runner import RoleRunner


def test_role_runner_dispatches_analyzer_role():
    runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": "Detected Django session auth",
                "evidence": ["users/views.py contains session cookie lookup"],
                "confidence": 0.93,
                "risk": "medium",
                "next_action": "send auth capability to planner",
                "blocking_issue": "none",
            }
        }
    )

    message = runner.run_role("Analyzer", {"site": "food"})

    assert isinstance(message, AgentMessage)
    assert message.role == "Analyzer"
    assert message.claim == "Detected Django session auth"


def test_role_runner_dispatches_all_supported_roles():
    runner = RoleRunner(
        responders={
            "Planner": lambda context: {
                "claim": "Need auth and order capabilities",
                "evidence": ["auth route and order route both detected"],
                "confidence": 0.88,
                "risk": "medium",
                "next_action": "ask generator for auth and order overlay",
                "blocking_issue": "none",
            }
        }
    )

    message = runner.run_role("Planner", {"site": "food"})

    assert message.role == "Planner"
    assert message.next_action == "ask generator for auth and order overlay"


def test_role_runner_can_wrap_message_as_event():
    runner = RoleRunner(
        responders={
            "Validator": lambda context: {
                "claim": "Runtime smoke test passed",
                "evidence": ["smoke-results.json contains zero failures"],
                "confidence": 0.95,
                "risk": "low",
                "next_action": "request export approval",
                "blocking_issue": "none",
            }
        }
    )

    message = runner.run_role("Validator", {"site": "food"})
    event = runner.build_event(
        run_id="food-run-001",
        event_type="validation.completed",
        state=RunState.VALIDATING,
        message=message,
        created_at="2026-03-15T23:30:00+09:00",
    )

    assert isinstance(event, RunEvent)
    assert event.run_id == "food-run-001"
    assert event.payload["role"] == "Validator"


def test_role_runner_rejects_unknown_role():
    runner = RoleRunner(responders={})

    try:
        runner.run_role("UnknownRole", {"site": "food"})
    except ValueError as exc:
        assert "Unsupported role" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown role")
