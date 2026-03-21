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

RUN_STATE_LABELS = {
    "queued": "준비 중",
    "analyzing": "구조 확인 중",
    "awaiting_analysis_approval": "분석 검토 대기",
    "planning": "변경 계획 정리 중",
    "generating": "변경안 생성 중",
    "awaiting_apply_approval": "적용 승인 대기",
    "applying": "변경 적용 중",
    "validating": "실행 검증 중",
    "diagnosing": "원인 분석 중",
    "awaiting_export_approval": "내보내기 승인 대기",
    "exporting": "결과 정리 중",
    "completed": "온보딩 준비 완료",
    "human_review_required": "사람 검토 필요",
    "failed": "진행 중단",
    "rejected": "승인 보류",
}

APPROVAL_LABELS = {
    "analysis": "분석",
    "apply": "적용",
    "export": "내보내기",
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
                "current_state": _display_run_state(current_state.value),
                "approval_status": _display_approval_status(approval_status),
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
                        "text": "진행",
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
                        "text": "보류",
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
                        {"type": "mrkdwn", "text": f"*상태*\n`{_display_run_state(current_state.value)}`"},
                        {"type": "mrkdwn", "text": f"*목표*\n{goal}"},
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"source root: `{source_root}`"},
                        {"type": "mrkdwn", "text": f"승인 상태: `{_display_approval_status(approval_status)}`"},
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
        approval_label = _display_approval_type(approval_value)
        request_id = payload["message"]["request_id"]
        blocks = [
            {
                "type": "divider",
            },
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"승인 확인: {approval_label}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*왜 필요한가*\n{_localize_approval_summary(summary)}\n\n"
                        f"*권장 응답*\n`{_display_recommended_option(recommended_option)}`"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*다음 단계*\n승인하면 진행하고, 거절하면 현재 단계에서 중단됩니다.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "진행"},
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
                        "text": {"type": "plain_text", "text": "보류"},
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
            text=f"승인 확인: {approval_label}",
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
            text=f"최종 결과: {_display_run_state(current_state)}",
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
    proposed_files = list(message.metadata.get("proposed_files") or [])
    proposed_patches = list(message.metadata.get("proposed_patches") or [])
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *요약*\n{localized_summary}",
            },
        },
    ]

    evidence_lines = "\n".join(f"- {item}" for item in message.evidence[:2]) or "- 상세 근거 없음"
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*핵심 근거*\n{evidence_lines}"},
        }
    )

    target_items = [Path(item).name for item in (proposed_files + proposed_patches)[:3]]
    if target_items:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*대상 파일*\n" + ", ".join(f"`{item}`" for item in target_items),
                },
            }
        )

    failure_reason = _derive_failure_reason(message)
    if failure_reason:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*실패 원인*\n{failure_reason}"},
            }
        )

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*다음 액션*\n{message.next_action}"},
        }
    )
    return blocks


def _build_summary_blocks(
    *,
    current_state: str,
    pending_approval: dict[str, Any] | None,
    artifacts: dict[str, Any],
) -> list[dict[str, Any]]:
    patch_proposal_lines: list[str] = []
    for label, value in artifacts.items():
        if value and label == "patch_proposal":
            patch_proposal_lines = _build_patch_proposal_lines(Path(value))

    blocks: list[dict[str, Any]] = [
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "최종 요약"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*상태*\n`{_display_run_state(current_state)}`"},
                {
                    "type": "mrkdwn",
                    "text": f"*대기 중 승인*\n`{_display_pending_approval(pending_approval)}`",
                },
            ],
        },
    ]
    if patch_proposal_lines:
        blocks.append(
            {
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": line} for line in patch_proposal_lines[:3]],
            }
        )
    runtime_failure_lines = _build_runtime_failure_lines(artifacts)
    if runtime_failure_lines:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*런타임 준비 실패*\n" + "\n".join(runtime_failure_lines[:2])},
            }
        )
    report_links = _build_report_link_lines(artifacts)
    if report_links:
        blocks.append(
            {
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": line} for line in report_links[:2]],
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
    normalized = decision.strip().lower()
    decision_label = "승인" if normalized in {"approve", "approved"} else "거절"
    return f"`{_display_approval_type(approval_value)}` 단계에 대해 `{decision_label}` 결정이 기록되었습니다."


def _build_patch_proposal_lines(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    target_files = list(payload.get("target_files") or [])
    supporting_generated_files = list(payload.get("supporting_generated_files") or [])
    analysis_summary = payload.get("analysis_summary") or {}

    generated_text = ", ".join(f"`{Path(item).name}`" for item in supporting_generated_files[:3]) or "none"
    target_text = ", ".join(f"`{item.get('path', 'unknown')}`" for item in target_files[:3]) or "none"

    reason_parts: list[str] = []
    auth_style = analysis_summary.get("auth_style")
    if auth_style:
        reason_parts.append(f"auth={auth_style}")
    mount_points = list(analysis_summary.get("frontend_mount_points") or [])
    if mount_points:
        reason_parts.append(f"mount={mount_points[0]}")
    route_prefixes = list(analysis_summary.get("route_prefixes") or [])
    if route_prefixes:
        reason_parts.append(f"route_prefix={route_prefixes[0]}")

    reason_text = ", ".join(reason_parts) or "탐지된 코드 구조를 기준으로 산출물을 선택했습니다."

    return [
        f"*만든 것*\n{generated_text}",
        f"*수정 대상*\n{target_text}",
        f"*핵심 판단*\n{reason_text}",
    ]


def _build_report_link_lines(artifacts: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label in ("backend_evaluation", "frontend_evaluation", "smoke_results", "recovery_plan"):
        value = artifacts.get(label)
        if value:
            lines.append(f"*보고서*\n`{value}`")
            break
    return lines


def _build_runtime_failure_lines(artifacts: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    backend_path = artifacts.get("backend_evaluation")
    if backend_path:
        try:
            payload = json.loads(Path(backend_path).read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        backend_bootstrap = payload.get("backend_bootstrap") or {}
        if backend_bootstrap.get("bootstrap_attempted") and not backend_bootstrap.get("bootstrap_passed", False):
            reason = str(backend_bootstrap.get("bootstrap_failure_reason") or "").strip()
            if reason:
                lines.append(f"- backend: {reason}")

    frontend_path = artifacts.get("frontend_build_validation")
    if frontend_path:
        try:
            payload = json.loads(Path(frontend_path).read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        reason = str(payload.get("bootstrap_failure_reason") or "").strip()
        if reason:
            lines.append(f"- frontend: {reason}")

    return lines


def _derive_failure_reason(message: AgentMessage) -> str | None:
    if message.role != "Diagnostician":
        return None
    if message.blocking_issue and str(message.blocking_issue).strip().lower() not in {"", "none"}:
        return str(message.blocking_issue)
    if message.evidence:
        return message.evidence[0]
    return None


def _display_run_state(state: str) -> str:
    return RUN_STATE_LABELS.get(state, state)


def _display_approval_type(approval_type: str) -> str:
    return APPROVAL_LABELS.get(approval_type, approval_type)


def _display_approval_status(status: str) -> str:
    if status == "not_requested":
        return "대기 없음"
    return _display_approval_type(status)


def _display_pending_approval(pending_approval: dict[str, Any] | None) -> str:
    if not pending_approval:
        return "없음"
    return _display_approval_type(str(pending_approval.get("approval_type", "없음")))


def _display_recommended_option(option: str) -> str:
    mapping = {
        "approve": "진행",
        "reject": "보류",
    }
    return mapping.get(option, option)
