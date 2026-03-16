from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

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
                "request_id": f"{run_id}:{approval_value}",
                "summary": summary,
                "recommended_option": recommended_option,
                "risk_if_approved": risk_if_approved,
                "risk_if_rejected": risk_if_rejected,
                "available_actions": available_actions,
                "actions": [
                    {
                        "text": "Approve",
                        "value": json.dumps(
                            {
                                "run_id": run_id,
                                "approval_type": approval_value,
                                "decision": "approve",
                                "request_id": f"{run_id}:{approval_value}",
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "text": "Reject",
                        "value": json.dumps(
                            {
                                "run_id": run_id,
                                "approval_type": approval_value,
                                "decision": "reject",
                                "request_id": f"{run_id}:{approval_value}",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
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
                "text": f"Approval decision recorded: {approval_value} -> {decision}",
            },
        }
        self.messages.append(payload)
        return payload


@dataclass
class SlackWebBridge(InMemorySlackBridge):
    web_client: Any = None
    _thread_ts_by_run_id: dict[str, str] = field(default_factory=dict)

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
        payload = super().post_run_root(
            run_id=run_id,
            site=site,
            source_root=source_root,
            goal=goal,
            current_state=current_state,
            approval_status=approval_status,
        )
        response = self.web_client.chat_postMessage(
            channel=self.channel,
            text=f"Onboarding run started: {run_id}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Onboarding run started*\nRun ID: `{run_id}`\nSite: `{site}`\nState: `{current_state.value}`",
                    },
                }
            ],
        )
        thread_ts = str(response.get("ts") or "")
        if thread_ts:
            self._thread_ts_by_run_id[run_id] = thread_ts
        return payload

    def post_agent_message(self, *, event: RunEvent, message: AgentMessage) -> dict:
        payload = super().post_agent_message(event=event, message=message)
        summary = _build_agent_summary_text(message)
        self.web_client.chat_postMessage(
            channel=self.channel,
            text=summary,
            thread_ts=self._thread_ts_by_run_id.get(event.run_id),
        )
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
        payload = super().post_approval_request(
            run_id=run_id,
            approval_type=approval_type,
            summary=summary,
            recommended_option=recommended_option,
            risk_if_approved=risk_if_approved,
            risk_if_rejected=risk_if_rejected,
            available_actions=available_actions,
        )
        approval_value = payload["message"]["approval_type"]
        request_id = payload["message"]["request_id"]
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Approval required: {approval_value}*\n"
                        f"{summary}\n"
                        f"Recommended: `{recommended_option}`"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "value": json.dumps(
                            {
                                "run_id": run_id,
                                "approval_type": approval_value,
                                "decision": "approve",
                                "request_id": request_id,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": json.dumps(
                            {
                                "run_id": run_id,
                                "approval_type": approval_value,
                                "decision": "reject",
                                "request_id": request_id,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
        ]
        self.web_client.chat_postMessage(
            channel=self.channel,
            text=f"Approval required: {approval_value}",
            blocks=blocks,
            thread_ts=self._thread_ts_by_run_id.get(run_id),
        )
        return payload


def _build_agent_summary_text(message: AgentMessage) -> str:
    text = f"{message.role}: {message.claim}"
    proposed_files = list(message.metadata.get("proposed_files") or [])
    proposed_patches = list(message.metadata.get("proposed_patches") or [])
    proposal_items = proposed_files + proposed_patches
    if proposal_items:
        names = ", ".join(Path(item).name for item in proposal_items[:3])
        text = f"{text} [{names}]"
    return text

    def record_approval_decision(
        self,
        *,
        run_id: str,
        approval_type: ApprovalType | str,
        decision: str,
    ) -> dict:
        payload = super().record_approval_decision(
            run_id=run_id,
            approval_type=approval_type,
            decision=decision,
        )
        self.web_client.chat_postMessage(
            channel=self.channel,
            text=payload["message"]["text"],
            thread_ts=self._thread_ts_by_run_id.get(run_id),
        )
        return payload
