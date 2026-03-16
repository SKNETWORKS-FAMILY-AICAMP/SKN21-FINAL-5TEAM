from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_contracts import ApprovalType, RunState


@dataclass
class AgentOrchestrator:
    run_id: str
    retry_budget: int = 3
    retry_count: int = 0
    state: RunState = RunState.QUEUED
    pending_approval: dict[str, Any] | None = None

    def mark_analysis_started(self) -> None:
        self.state = RunState.ANALYZING

    def request_analysis_approval(self, *, summary: str, recommended_option: str) -> dict[str, Any]:
        self.state = RunState.AWAITING_ANALYSIS_APPROVAL
        self.pending_approval = self._build_approval_payload(
            approval_type=ApprovalType.ANALYSIS,
            summary=summary,
            recommended_option=recommended_option,
        )
        return self.pending_approval

    def mark_analysis_completed(self) -> None:
        self.state = RunState.PLANNING
        self.pending_approval = None

    def mark_plan_completed(self) -> None:
        self.state = RunState.GENERATING

    def request_apply_approval(self, *, summary: str, recommended_option: str) -> dict[str, Any]:
        self.state = RunState.AWAITING_APPLY_APPROVAL
        self.pending_approval = self._build_approval_payload(
            approval_type=ApprovalType.APPLY,
            summary=summary,
            recommended_option=recommended_option,
        )
        return self.pending_approval

    def approve_apply(self) -> None:
        self.state = RunState.APPLYING
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
        )
        return self.pending_approval

    def approve_export(self) -> None:
        self.state = RunState.EXPORTING
        self.pending_approval = None

    def mark_export_completed(self) -> None:
        self.state = RunState.COMPLETED

    def reject_current_approval(self) -> None:
        self.pending_approval = None
        self.state = RunState.REJECTED

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
    ) -> dict[str, Any]:
        return {
            "approval_type": approval_type.value,
            "summary": summary,
            "recommended_option": recommended_option,
            "status": "pending",
        }
