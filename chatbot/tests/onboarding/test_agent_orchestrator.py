import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import RunState
from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator


def test_agent_orchestrator_moves_through_core_states():
    orchestrator = AgentOrchestrator(run_id="food-run-001")

    assert orchestrator.state == RunState.QUEUED

    orchestrator.mark_analysis_started()
    assert orchestrator.state == RunState.ANALYZING

    orchestrator.mark_analysis_completed()
    assert orchestrator.state == RunState.PLANNING

    orchestrator.mark_plan_completed()
    assert orchestrator.state == RunState.GENERATING


def test_agent_orchestrator_waits_for_apply_approval():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.mark_analysis_started()
    orchestrator.mark_analysis_completed()
    orchestrator.mark_plan_completed()

    orchestrator.request_apply_approval(
        summary="Overlay bundle is ready to apply",
        recommended_option="approve",
    )
    assert orchestrator.state == RunState.AWAITING_APPLY_APPROVAL

    orchestrator.approve_apply()
    assert orchestrator.state == RunState.APPLYING

    orchestrator.mark_apply_completed()
    assert orchestrator.state == RunState.VALIDATING


def test_agent_orchestrator_transitions_to_diagnosing_on_failure():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.mark_analysis_started()

    orchestrator.mark_failure()

    assert orchestrator.state == RunState.DIAGNOSING
    assert orchestrator.retry_count == 1


def test_agent_orchestrator_moves_to_human_review_when_retry_budget_exceeded():
    orchestrator = AgentOrchestrator(run_id="food-run-001", retry_budget=2)

    orchestrator.mark_failure()
    assert orchestrator.state == RunState.DIAGNOSING

    orchestrator.mark_failure()
    assert orchestrator.state == RunState.HUMAN_REVIEW_REQUIRED
    assert orchestrator.retry_count == 2


def test_agent_orchestrator_can_finish_export_flow():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.mark_analysis_started()
    orchestrator.mark_analysis_completed()
    orchestrator.mark_plan_completed()
    orchestrator.request_apply_approval(
        summary="Overlay bundle is ready to apply",
        recommended_option="approve",
    )
    orchestrator.approve_apply()
    orchestrator.mark_apply_completed()
    orchestrator.mark_validation_completed()

    assert orchestrator.state == RunState.AWAITING_EXPORT_APPROVAL

    orchestrator.request_export_approval(
        summary="Patch export is ready",
        recommended_option="approve",
    )
    orchestrator.approve_export()
    assert orchestrator.state == RunState.EXPORTING

    orchestrator.mark_export_completed()
    assert orchestrator.state == RunState.COMPLETED
