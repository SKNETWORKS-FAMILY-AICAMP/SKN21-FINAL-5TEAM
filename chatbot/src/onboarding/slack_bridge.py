from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .agent_contracts import AgentMessage, ApprovalType, RunEvent, RunState


@dataclass
class InMemorySlackBridge:
    channel: str
    messages: list[dict] = field(default_factory=list)

    def post_run_root(
        self,
        *,
        run_id: str,
        site: str,
        source_root: str,
        goal: str,
        current_state: RunState,
        approval_status: str,
    ) -> dict:
        payload = {
            "channel": self.channel,
            "thread_key": run_id,
            "message": {
                "run_id": run_id,
                "site": site,
                "source_root": source_root,
                "goal": goal,
                "current_state": current_state.value,
                "approval_status": approval_status,
            },
        }
        self.messages.append(payload)
        return payload

    def post_agent_message(self, *, event: RunEvent, message: AgentMessage) -> dict:
        payload = {
            "channel": self.channel,
            "thread_key": event.run_id,
            "message": {
                "event_type": event.event_type,
                "state": event.state.value,
                **message.model_dump(),
            },
        }
        self.messages.append(payload)
        return payload

    def post_approval_request(
        self,
        *,
        run_id: str,
        approval_type: ApprovalType | str,
        summary: str,
        recommended_option: str,
        risk_if_approved: str,
        risk_if_rejected: str,
        available_actions: list[str],
    ) -> dict:
        approval_value = approval_type.value if isinstance(approval_type, Enum) else str(approval_type)
        payload = {
            "channel": self.channel,
            "thread_key": run_id,
            "message": {
                "approval_type": approval_value,
                "summary": summary,
                "recommended_option": recommended_option,
                "risk_if_approved": risk_if_approved,
                "risk_if_rejected": risk_if_rejected,
                "available_actions": available_actions,
            },
        }
        self.messages.append(payload)
        return payload

    def record_approval_decision(
        self,
        *,
        run_id: str,
        approval_type: ApprovalType | str,
        decision: str,
    ) -> dict:
        approval_value = approval_type.value if isinstance(approval_type, Enum) else str(approval_type)
        payload = {
            "channel": self.channel,
            "thread_key": run_id,
            "message": {
                "approval_type": approval_value,
                "decision": decision,
            },
        }
        self.messages.append(payload)
        return payload
