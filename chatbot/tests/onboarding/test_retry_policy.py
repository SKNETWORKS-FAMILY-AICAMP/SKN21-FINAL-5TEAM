import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator
from chatbot.src.onboarding.agent_contracts import RunState
from chatbot.src.onboarding.orchestrator import _run_validation_with_retries
from chatbot.src.onboarding.role_runner import RoleRunner
from chatbot.src.onboarding.smoke_contract import SmokeTestPlan, SmokeTestStep


def _role_runner(should_retry: bool) -> RoleRunner:
    return RoleRunner(
        responders={
            "Diagnostician": lambda context: {
                "claim": "diagnose retry policy",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "retry_validation" if should_retry else "request_human_review",
                "blocking_issue": "none" if should_retry else "structural failure",
                "metadata": {"should_retry": should_retry},
            }
        }
    )


def test_retry_policy_does_not_retry_missing_script_failure(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        return [
            {
                "step": "smoke-tests/missing.sh",
                "step_id": "missing",
                "returncode": 127,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "",
                "stderr": "Smoke script not found: /tmp/missing.sh",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-001")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-001",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="missing", script="smoke-tests/missing.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
    )

    assert results[0]["returncode"] == 127
    assert smoke_calls["count"] == 1
    assert agent.retry_count == 0
    assert agent.state == RunState.HUMAN_REVIEW_REQUIRED


def test_retry_policy_retries_transient_timeout_once(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [
                {
                    "step": "smoke-tests/login.sh",
                    "step_id": "login",
                    "returncode": 124,
                    "required": True,
                    "category": "auth",
                    "timed_out": True,
                    "stdout": "",
                    "stderr": "",
                }
            ]
        return [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-001")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-001",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="login", script="smoke-tests/login.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
    )

    assert smoke_calls["count"] == 2
    assert agent.retry_count == 1
    assert agent.state == RunState.VALIDATING
    assert results[0]["returncode"] == 0
