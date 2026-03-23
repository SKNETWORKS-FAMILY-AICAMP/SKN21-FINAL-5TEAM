from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_contracts import ApprovalType, RunState


@dataclass
class AgentOrchestrator:
    run_id: str
    retry_budget: int = 3
    retry_count: int = 0
    state: RunState = RunState.QUEUED
    pending_approval: dict[str, Any] | None = None
    blocked_jobs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def mark_analysis_started(self) -> None:
        self.state = RunState.ANALYZING

    def request_analysis_approval(self, *, summary: str, recommended_option: str) -> dict[str, Any]:
        self.state = RunState.AWAITING_ANALYSIS_APPROVAL
        self.pending_approval = self._build_approval_payload(
            approval_type=ApprovalType.ANALYSIS,
            summary=summary,
            recommended_option=recommended_option,
            blocked_job_id="planning",
        )
        self._block_job("planning", ApprovalType.ANALYSIS)
        return self.pending_approval

    def mark_analysis_completed(self) -> None:
        self.state = RunState.PLANNING
        self._unblock_job("planning")
        self.pending_approval = None

    def mark_plan_completed(self) -> None:
        self.state = RunState.GENERATING

    def request_apply_approval(self, *, summary: str, recommended_option: str) -> dict[str, Any]:
        self.state = RunState.AWAITING_APPLY_APPROVAL
        self.pending_approval = self._build_approval_payload(
            approval_type=ApprovalType.APPLY,
            summary=summary,
            recommended_option=recommended_option,
            blocked_job_id="apply",
        )
        self._block_job("apply", ApprovalType.APPLY)
        return self.pending_approval

    def approve_apply(self) -> None:
        self.state = RunState.APPLYING
        self._unblock_job("apply")
        self.pending_approval = None

    def mark_apply_completed(self) -> None:
        self.state = RunState.VALIDATING

    def mark_validation_completed(self) -> None:
        self.state = RunState.AWAITING_EXPORT_APPROVAL

    def request_export_approval(self, *, summary: str, recommended_option: str) -> dict[str, Any]:
        self.state = RunState.AWAITING_EXPORT_APPROVAL
        self.pending_approval = self._build_approval_payload(
            approval_type=ApprovalType.EXPORT,
            summary=summary,
            recommended_option=recommended_option,
            blocked_job_id="export",
        )
        self._block_job("export", ApprovalType.EXPORT)
        return self.pending_approval

    def approve_export(self) -> None:
        self.state = RunState.EXPORTING
        self._unblock_job("export")
        self.pending_approval = None

    def mark_export_completed(self) -> None:
        self.state = RunState.COMPLETED

    def reject_current_approval(self) -> None:
        if self.pending_approval is not None:
            blocked_job_id = str(self.pending_approval.get("blocked_job_id") or "")
            if blocked_job_id:
                self.blocked_jobs.setdefault(blocked_job_id, {})["status"] = "rejected"
        self.pending_approval = None
        self.state = RunState.REJECTED

    def is_job_blocked(self, job_id: str) -> bool:
        payload = self.blocked_jobs.get(job_id)
        return bool(payload and payload.get("status") == "blocked")

    def mark_failure(self) -> None:
        self.retry_count += 1
        if self.retry_count >= self.retry_budget:
            self.state = RunState.HUMAN_REVIEW_REQUIRED
            return
        self.state = RunState.DIAGNOSING

    def _build_approval_payload(
        self,
        *,
        approval_type: ApprovalType,
        summary: str,
        recommended_option: str,
        blocked_job_id: str,
    ) -> dict[str, Any]:
        return {
            "approval_type": approval_type.value,
            "summary": summary,
            "recommended_option": recommended_option,
            "status": "pending",
            "blocked_job_id": blocked_job_id,
        }

    def _block_job(self, job_id: str, approval_type: ApprovalType) -> None:
        self.blocked_jobs[job_id] = {
            "job_id": job_id,
            "approval_type": approval_type.value,
            "status": "blocked",
        }

    def _unblock_job(self, job_id: str) -> None:
        if job_id not in self.blocked_jobs:
            return
        self.blocked_jobs[job_id]["status"] = "unblocked"
