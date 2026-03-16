import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import ApprovalType, RunState
from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator


def test_request_analysis_approval_creates_pending_gate():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    gate = orchestrator.request_analysis_approval(
        summary="Analyzer found cookie-based auth and order endpoints",
        recommended_option="approve",
    )

    assert orchestrator.state == RunState.AWAITING_ANALYSIS_APPROVAL
    assert gate["approval_type"] == ApprovalType.ANALYSIS.value
    assert gate["status"] == "pending"


def test_request_apply_approval_keeps_orchestrator_waiting_until_approved():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.mark_analysis_started()
    orchestrator.mark_analysis_completed()
    orchestrator.mark_plan_completed()

    gate = orchestrator.request_apply_approval(
        summary="Overlay bundle is ready to apply",
        recommended_option="approve",
    )

    assert orchestrator.state == RunState.AWAITING_APPLY_APPROVAL
    assert gate["approval_type"] == ApprovalType.APPLY.value

    orchestrator.approve_apply()
    assert orchestrator.state == RunState.APPLYING


def test_request_export_approval_keeps_orchestrator_waiting_until_approved():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.mark_analysis_started()
    orchestrator.mark_analysis_completed()
    orchestrator.mark_plan_completed()
    orchestrator.request_apply_approval(summary="ready", recommended_option="approve")
    orchestrator.approve_apply()
    orchestrator.mark_apply_completed()
    orchestrator.mark_validation_completed()

    gate = orchestrator.request_export_approval(
        summary="Patch export is ready",
        recommended_option="approve",
    )

    assert orchestrator.state == RunState.AWAITING_EXPORT_APPROVAL
    assert gate["approval_type"] == ApprovalType.EXPORT.value

    orchestrator.approve_export()
    assert orchestrator.state == RunState.EXPORTING


def test_rejecting_approval_moves_run_to_rejected():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.request_analysis_approval(
        summary="Analyzer found cookie-based auth",
        recommended_option="approve",
    )

    orchestrator.reject_current_approval()

    assert orchestrator.state == RunState.REJECTED
