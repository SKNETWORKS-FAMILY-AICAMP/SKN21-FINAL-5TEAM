from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from slack_sdk.errors import SlackApiError

from .agent_contracts import AgentMessage, ApprovalType, RunEvent, RunState


ROLE_STYLE = {
    "Analyzer": {"emoji": ":mag:", "label": "Onboarding Analyzer"},
    "Planner": {"emoji": ":triangular_ruler:", "label": "Onboarding Planner"},
    "Generator": {"emoji": ":hammer_and_wrench:", "label": "Onboarding Generator"},
    "Validator": {"emoji": ":white_check_mark:", "label": "Onboarding Validator"},
    "Diagnostician": {"emoji": ":stethoscope:", "label": "Onboarding Diagnostician"},
}

ROLE_SUMMARY_PREFIX = {
    "Analyzer": "분석 결과를 공유합니다.",
    "Planner": "계획 수립 결과를 공유합니다.",
    "Generator": "생성 결과를 공유합니다.",
    "Validator": "검증 결과를 공유합니다.",
    "Diagnostician": "장애 분석 결과를 공유합니다.",
}


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
                "kind": "run_root",
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
                "kind": "agent",
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
                "kind": "approval_request",
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
                "kind": "approval_decision",
                "approval_type": approval_value,
                "decision": decision,
                "text": f"Approval decision recorded: {approval_value} -> {decision}",
            },
        }
        self.messages.append(payload)
        return payload

    def post_run_summary(
        self,
        *,
        run_id: str,
        current_state: str,
        pending_approval: dict[str, Any] | None,
        artifacts: dict[str, Any],
    ) -> dict:
        payload = {
            "channel": self.channel,
            "thread_key": run_id,
            "message": {
                "kind": "run_summary",
                "current_state": current_state,
                "pending_approval": pending_approval,
                "artifacts": artifacts,
            },
        }
        self.messages.append(payload)
        return payload


@dataclass
class SlackWebBridge(InMemorySlackBridge):
    web_client: Any = None
    role_web_clients: dict[str, Any] = field(default_factory=dict)
    conversation_mode: str = "channel"
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
        response = self._chat_post_message(
            run_id=run_id,
            persona_name="Onboarding Coordinator",
            icon_emoji=":satellite:",
            text=f"온보딩 실행 시작: {run_id}",
            blocks=[
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "온보딩 실행 시작"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Run ID*\n`{run_id}`"},
                        {"type": "mrkdwn", "text": f"*사이트*\n`{site}`"},
                        {"type": "mrkdwn", "text": f"*상태*\n`{current_state.value}`"},
                        {"type": "mrkdwn", "text": f"*목표*\n{goal}"},
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"source root: `{source_root}`"},
                        {"type": "mrkdwn", "text": f"approval: `{approval_status}`"},
                    ],
                },
            ],
        )
        thread_ts = str(response.get("ts") or "")
        if thread_ts:
            self._thread_ts_by_run_id[run_id] = thread_ts
        return payload

    def post_agent_message(self, *, event: RunEvent, message: AgentMessage) -> dict:
        payload = super().post_agent_message(event=event, message=message)
        role_style = ROLE_STYLE.get(message.role, {"emoji": ":speech_balloon:", "label": message.role})
        self._chat_post_message(
            run_id=event.run_id,
            persona_name=role_style["label"],
            icon_emoji=role_style["emoji"],
            text=_build_agent_summary_text(message),
            blocks=_build_agent_blocks(
                role=message.role,
                emoji=role_style["emoji"],
                event_type=event.event_type,
                state=event.state.value,
                message=message,
            ),
            web_client=self.role_web_clients.get(message.role, self.web_client),
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
                "type": "divider",
            },
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Approval Required: {approval_value}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*요약*\n{_localize_approval_summary(summary)}\n\n*권장 응답*\n`{recommended_option}`",
                },
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"승인 시 영향: {risk_if_approved}"},
                    {"type": "mrkdwn", "text": f"거절 시 영향: {risk_if_rejected}"},
                ],
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
        self._chat_post_message(
            run_id=run_id,
            persona_name="Approval Gate",
            icon_emoji=":rotating_light:",
            text=f"승인 필요: {approval_value}",
            blocks=blocks,
        )
        return payload

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
        self._chat_post_message(
            run_id=run_id,
            persona_name="Approval Recorder",
            icon_emoji=":memo:",
            text=_localize_decision_text(approval_value=payload["message"]["approval_type"], decision=decision),
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": _localize_decision_text(
                            approval_value=payload["message"]["approval_type"],
                            decision=decision,
                        ),
                    },
                }
            ],
        )
        return payload

    def post_run_summary(
        self,
        *,
        run_id: str,
        current_state: str,
        pending_approval: dict[str, Any] | None,
        artifacts: dict[str, Any],
    ) -> dict:
        payload = super().post_run_summary(
            run_id=run_id,
            current_state=current_state,
            pending_approval=pending_approval,
            artifacts=artifacts,
        )
        self._chat_post_message(
            run_id=run_id,
            persona_name="Run Reporter",
            icon_emoji=":bookmark_tabs:",
            text=f"실행 요약: {current_state}",
            blocks=_build_summary_blocks(
                current_state=current_state,
                pending_approval=pending_approval,
                artifacts=artifacts,
            ),
        )
        return payload

    def _chat_post_message(
        self,
        *,
        run_id: str,
        persona_name: str,
        icon_emoji: str,
        text: str,
        blocks: list[dict[str, Any]],
        web_client: Any | None = None,
    ) -> dict[str, Any]:
        active_web_client = web_client or self.web_client
        kwargs: dict[str, Any] = {
            "channel": self.channel,
            "text": text,
            "blocks": blocks,
            "username": persona_name,
            "icon_emoji": icon_emoji,
        }
        thread_ts = self._thread_ts_by_run_id.get(run_id) if self.conversation_mode == "thread" else None
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            return active_web_client.chat_postMessage(**kwargs)
        except SlackApiError as exc:
            if exc.response.get("error") != "missing_scope":
                raise
            fallback = dict(kwargs)
            fallback.pop("username", None)
            fallback.pop("icon_emoji", None)
            return active_web_client.chat_postMessage(**fallback)


def _build_agent_summary_text(message: AgentMessage) -> str:
    text = f"[{message.role}] {_localize_agent_summary(message)}"
    proposed_files = list(message.metadata.get("proposed_files") or [])
    proposed_patches = list(message.metadata.get("proposed_patches") or [])
    proposal_items = proposed_files + proposed_patches
    if proposal_items:
        names = ", ".join(Path(item).name for item in proposal_items[:3])
        text = f"{text} [{names}]"
    return text


def _build_agent_blocks(
    *,
    role: str,
    emoji: str,
    event_type: str,
    state: str,
    message: AgentMessage,
) -> list[dict[str, Any]]:
    localized_summary = _localize_agent_summary(message)
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{role} 요약*\n{localized_summary}",
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"event: `{event_type}`"},
                {"type": "mrkdwn", "text": f"state: `{state}`"},
                {"type": "mrkdwn", "text": f"risk: `{message.risk}`"},
                {"type": "mrkdwn", "text": f"confidence: `{message.confidence:.2f}`"},
            ],
        },
    ]
    if message.evidence:
        evidence_lines = "\n".join(f"- {item}" for item in message.evidence[:4])
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*상세 근거*\n{evidence_lines}"},
            }
        )
    metadata_lines = _build_metadata_lines(message.metadata)
    if metadata_lines:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*상세 산출물*\n" + "\n".join(metadata_lines)},
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"next: {message.next_action}"},
                {"type": "mrkdwn", "text": f"blocking: {message.blocking_issue}"},
            ],
        }
    )
    return blocks


def _build_metadata_lines(metadata: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    proposed_files = list(metadata.get("proposed_files") or [])
    proposed_patches = list(metadata.get("proposed_patches") or [])
    if proposed_files:
        lines.append("files: " + ", ".join(f"`{Path(item).name}`" for item in proposed_files[:3]))
    if proposed_patches:
        lines.append("patches: " + ", ".join(f"`{Path(item).name}`" for item in proposed_patches[:3]))
    if metadata.get("should_retry") is not None:
        lines.append(f"retry suggested: `{bool(metadata['should_retry'])}`")
    return lines


def _build_summary_blocks(
    *,
    current_state: str,
    pending_approval: dict[str, Any] | None,
    artifacts: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_lines = []
    for label, value in artifacts.items():
        if value:
            artifact_lines.append(f"*{label}*\n`{value}`")
    blocks: list[dict[str, Any]] = [
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "실행 요약"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*상태*\n`{current_state}`"},
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*대기 중 승인*\n`{(pending_approval or {}).get('approval_type', 'none')}`"
                    ),
                },
            ],
        },
    ]
    if artifact_lines:
        blocks.append(
            {
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": line} for line in artifact_lines[:6]],
            }
        )
    return blocks


def _localize_agent_summary(message: AgentMessage) -> str:
    prefix = ROLE_SUMMARY_PREFIX.get(message.role, "에이전트 결과를 공유합니다.")
    return f"{prefix} {message.claim}"


def _localize_approval_summary(summary: str) -> str:
    mapping = {
        "Analysis is ready for review": "분석 결과 검토가 필요합니다.",
        "Overlay bundle is ready to apply": "생성된 변경안을 적용해도 되는지 확인이 필요합니다.",
        "Export bundle is ready": "최종 산출물을 내보내도 되는지 확인이 필요합니다.",
    }
    return mapping.get(summary, summary)


def _localize_decision_text(*, approval_value: str, decision: str) -> str:
    decision_label = "승인" if decision == "approve" else "거절"
    return f"`{approval_value}` 단계에 대해 `{decision_label}` 결정이 기록되었습니다."
