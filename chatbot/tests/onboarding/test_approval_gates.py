import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import ApprovalType, RunState
from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator
from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.redis_store import RedisRunJobStore
from chatbot.src.onboarding.redis_models import RunRecord
from chatbot.src.onboarding.orchestrator import _apply_approval_decision, _publish_approval_requested_event


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs) -> None:
        if mapping is None:
            mapping = {}
        self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key) or {})

    def sadd(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self._lists.get(key, [])
        if stop < 0:
            stop = len(values) + stop
        if stop < 0:
            return []
        stop = min(stop, len(values) - 1)
        if start >= len(values):
            return []
        return list(values[start : stop + 1])


def test_request_analysis_approval_creates_pending_gate():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    gate = orchestrator.request_analysis_approval(
        summary="Analyzer found cookie-based auth and order endpoints",
        recommended_option="approve",
    )

    assert orchestrator.state == RunState.AWAITING_ANALYSIS_APPROVAL
    assert gate["approval_type"] == ApprovalType.ANALYSIS.value
    assert gate["status"] == "pending"
    assert orchestrator.is_job_blocked("planning")
    assert gate["blocked_job_id"] == "planning"


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
    assert orchestrator.is_job_blocked("apply")

    orchestrator.approve_apply()
    assert orchestrator.state == RunState.APPLYING
    assert not orchestrator.is_job_blocked("apply")


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
    assert orchestrator.is_job_blocked("export")

    orchestrator.approve_export()
    assert orchestrator.state == RunState.EXPORTING
    assert not orchestrator.is_job_blocked("export")


def test_rejecting_approval_moves_run_to_rejected():
    orchestrator = AgentOrchestrator(run_id="food-run-001")
    orchestrator.request_analysis_approval(
        summary="Analyzer found cookie-based auth",
        recommended_option="approve",
    )

    orchestrator.reject_current_approval()

    assert orchestrator.state == RunState.REJECTED
    assert orchestrator.blocked_jobs["planning"]["status"] == "rejected"


def test_approval_request_emits_event_and_approval_decision_unblocks_job(tmp_path: Path):
    approval_store = ApprovalStore(root=tmp_path / "approvals")
    fake = _FakeRedis()
    event_store = RedisRunJobStore(fake)
    run_id = "food-run-approval-events"
    event_store.create_run(RunRecord(run_id=run_id, metadata={"site": "food"}))
    orchestrator = AgentOrchestrator(run_id=run_id)

    gate = orchestrator.request_analysis_approval(
        summary="Analysis is ready for review",
        recommended_option="approve",
    )
    approval_store.create_request(
        run_id=run_id,
        approval_type="analysis",
        blocked_job_id=gate["blocked_job_id"],
    )
    _publish_approval_requested_event(event_store, run_id, gate)

    entries = [json.loads(entry) for entry in fake.lrange(f"onboarding:events:{run_id}", 0, -1)]
    assert entries[-1]["event"] == "approval.requested"
    assert entries[-1]["payload"]["approval_type"] == "analysis"
    assert entries[-1]["payload"]["blocked_job_id"] == "planning"
    assert orchestrator.is_job_blocked("planning")

    approval_store.record_decision(
        run_id=run_id,
        approval_type="analysis",
        decision="approve",
        actor="tester",
    )
    result = _apply_approval_decision(
        agent=orchestrator,
        approval_type="analysis",
        decisions=None,
        approval_store=approval_store,
    )

    assert result == "approved"
    assert orchestrator.state == RunState.PLANNING
    assert not orchestrator.is_job_blocked("planning")
