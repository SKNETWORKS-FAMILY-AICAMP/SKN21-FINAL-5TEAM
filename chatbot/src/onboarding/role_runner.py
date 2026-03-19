from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from chatbot.src.graph.llm_providers import make_chat_llm

from .agent_contracts import AgentMessage, RunEvent, RunState
from .debug_logging import (
    append_generation_log,
    append_llm_usage,
    append_onboarding_event,
    extract_llm_usage,
    write_llm_debug_artifact,
)


SUPPORTED_ROLES = {
    "Analyzer",
    "Planner",
    "Generator",
    "Validator",
    "Diagnostician",
}


@dataclass
class RoleRunner:
    responders: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = field(
        default_factory=dict
    )

    def run_role(self, role: str, context: dict[str, Any]) -> AgentMessage:
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"Unsupported role: {role}")

        responder = self.responders.get(role)
        if responder is None:
            raise ValueError(f"Unsupported role: {role}")

        payload = responder(context)
        return AgentMessage(role=role, **payload)

    def build_event(
        self,
        *,
        run_id: str,
        event_type: str,
        state: RunState,
        message: AgentMessage,
        created_at: str,
    ) -> RunEvent:
        return RunEvent(
            event_type=event_type,
            run_id=run_id,
            state=state,
            payload=message.model_dump(),
            created_at=created_at,
        )


ROLE_SYSTEM_PROMPTS = {
    "Analyzer": """You are the Analyzer role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.
Write all human-facing values in Korean (한국어). This includes claim, evidence items, risk, next_action, and blocking_issue.
Keep file paths, route strings, capability names, framework names, and code identifiers unchanged when needed.
confidence must be a JSON number between 0 and 1. Do not return percentages or strings for confidence.
evidence must be a JSON array of strings.
next_action must be a single string. Do not return arrays for next_action.
blocking_issue must be a single string or null.

Your job:
- Read the provided repository evidence and infer only what is directly supported.
- Map findings to these capability names when justified by evidence:
  - auth.login_state_detection
  - auth.chat_token_issue
  - catalog.product_list
  - catalog.product_detail
  - orders.list
  - orders.detail
  - orders.action
  - frontend.widget_mount
- If evidence is weak or ambiguous, say so explicitly and lower confidence.
- Do not invent routes, files, auth mechanisms, or framework behavior.

metadata must be an object and should include:
- capabilities: array of capability names supported by evidence
- auth_signals: array of auth-related signals
- api_signals: array of product/order route signals
- unknowns: array of unresolved questions
""",
    "Planner": """You are the Planner role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.
Write all human-facing values in Korean (한국어). This includes claim, evidence items, risk, next_action, and blocking_issue.
Keep file paths, route strings, capability names, framework names, and code identifiers unchanged when needed.
confidence must be a JSON number between 0 and 1. Do not return percentages or strings for confidence.
evidence must be a JSON array of strings.
next_action must be a single string. Do not return arrays for next_action.
blocking_issue must be a single string or null.

Your job:
- Use the analysis output to decide which capabilities should be implemented first.
- Be explicit about missing_capabilities and risks before generation.
- Prioritize auth.chat_token_issue and orders/catalog capabilities before frontend polish when those are missing.
- Use backend_strategy, frontend_strategy, backend_route_targets, frontend_mount_targets, and tool registry wiring targets when deciding generation order.
- Do not invent routes, capabilities, or implementation status.
- Do not propose deployment, direct production edits, or bypassing runtime copy / approval gates.

metadata must be an object and should include:
- priority_capabilities: array
- missing_capabilities: array
- recommended_outputs: array
- approval_risks: array
- backend_strategy: string
- frontend_strategy: string

Use the term capabilities explicitly in your reasoning.
Mention runtime copy when discussing execution safety.
Mention tool registry wiring when backend adapters are needed.
""",
    "Generator": """You are the Generator role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.
Write all human-facing values in Korean (한국어). This includes claim, evidence items, risk, next_action, and blocking_issue.
Keep file paths, route strings, capability names, framework names, and code identifiers unchanged when needed.
confidence must be a JSON number between 0 and 1. Do not return percentages or strings for confidence.
evidence must be a JSON array of strings.
next_action must be a single string. Do not return arrays for next_action.
blocking_issue must be a single string or null.

Your job:
- Propose what overlay artifacts should be produced next based on analysis and recommended outputs.
- Focus on file-level and patch-level proposals, not full implementations.
- Do not output full code or long patch bodies.
- Keep proposals aligned with runtime copy / overlay application flow.

metadata must be an object and should include:
- proposed_files: array
- proposed_patches: array
- patch_intents: array
- generation_risks: array
""",
    "Validator": """You are the Validator role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.
Write all human-facing values in Korean (한국어). This includes claim, evidence items, risk, next_action, and blocking_issue.
Keep file paths, route strings, capability names, framework names, and code identifiers unchanged when needed.
confidence must be a JSON number between 0 and 1. Do not return percentages or strings for confidence.
evidence must be a JSON array of strings.
next_action must be a single string. Do not return arrays for next_action.
blocking_issue must be a single string or null.

Your job:
- Assess validation from smoke_results and related evidence.
- Identify failed_steps explicitly when any smoke step failed.
- Provide an approval recommendation implicitly via next_action: either request export approval or send failure to diagnostician.
- Do not claim success if any smoke step failed.
- Be specific about failure_count, failed_steps, and the highest-risk failure.

metadata must be an object and should include:
- failed_steps: array
- failure_count: integer
- validation_status: passed | failed
- approval_recommendation: request_export_approval | diagnose_failure
""",
    "Diagnostician": """You are the Diagnostician role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.
Write all human-facing values in Korean (한국어). This includes claim, evidence items, risk, next_action, and blocking_issue.
Keep file paths, route strings, capability names, framework names, and code identifiers unchanged when needed.
confidence must be a JSON number between 0 and 1. Do not return percentages or strings for confidence.
evidence must be a JSON array of strings.
next_action must be a single string. Do not return arrays for next_action.
blocking_issue must be a single string or null.

Your job:
- Read the failure_signature, retry budget, and validation evidence.
- Produce a root_cause_hypothesis and proposed_fix.
- Decide conservatively whether retry is justified.
- Treat missing scripts, missing patch targets, and hard auth mismatches as structural failures that should not retry.
- Use retry budget explicitly; if budget is exhausted, do not recommend retry.

metadata must be an object and should include:
- classification: string
- should_retry: boolean
- root_cause_hypothesis: string
- proposed_fix: string
- failure_signature: string
Use metadata.should_retry as a boolean when recommending a retry.
""",
}


@dataclass
class LLMRoleRunner:
    llm_factory: Callable[[], Any]
    provider: str | None = None
    model: str | None = None
    last_raw_response: str | None = None
    last_usage: dict[str, Any] = field(default_factory=dict)
    last_parse_metadata: dict[str, Any] = field(default_factory=dict)

    def run_role(self, role: str, context: dict[str, Any]) -> AgentMessage:
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"Unsupported role: {role}")

        llm = self.llm_factory()
        response = llm.invoke(
            [
                SystemMessage(content=ROLE_SYSTEM_PROMPTS[role]),
                HumanMessage(content=json.dumps(context, ensure_ascii=False, indent=2)),
            ]
        )
        self.last_raw_response = str(response.content)
        self.last_usage = extract_llm_usage(response)
        payload, parse_metadata = _parse_json_payload(response.content)
        self.last_parse_metadata = parse_metadata
        return AgentMessage(role=role, **payload)

    def build_event(
        self,
        *,
        run_id: str,
        event_type: str,
        state: RunState,
        message: AgentMessage,
        created_at: str,
    ) -> RunEvent:
        return RunEvent(
            event_type=event_type,
            run_id=run_id,
            state=state,
            payload=message.model_dump(),
            created_at=created_at,
        )


@dataclass
class ReliableLLMRoleRunner:
    llm_runner: LLMRoleRunner
    fallback_runner: RoleRunner
    execution_log: dict[str, dict[str, Any]] = field(default_factory=dict)
    debug_log: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage_events: list[dict[str, Any]] = field(default_factory=list)

    def run_role(self, role: str, context: dict[str, Any]) -> AgentMessage:
        try:
            message = self.llm_runner.run_role(role, context)
            parse_metadata = self.llm_runner.last_parse_metadata or {}
            source = "recovered_llm" if parse_metadata.get("recovery_applied") else "llm"
            self.execution_log[role] = {
                "source": source,
                "fallback_reason": None,
                "recovery_reason": parse_metadata.get("recovery_reason"),
            }
            self.debug_log[role] = {
                "status": source,
                "fallback_reason": None,
                "recovery_reason": parse_metadata.get("recovery_reason"),
                "raw_response": self.llm_runner.last_raw_response or "",
                "normalized_response": parse_metadata.get("normalized_payload"),
                "usage": self.llm_runner.last_usage,
            }
            self.usage_events.append(
                {
                    "component": f"role:{role}",
                    "provider": self.llm_runner.provider,
                    "model": self.llm_runner.model,
                    "usage": dict(self.llm_runner.last_usage),
                    "details": {
                        "status": source,
                        "recovery_reason": parse_metadata.get("recovery_reason"),
                    },
                }
            )
            return message
        except json.JSONDecodeError:
            return self._fallback(role, context, "invalid_llm_response")
        except ValidationError:
            return self._fallback(role, context, "invalid_llm_payload")
        except Exception:
            return self._fallback(role, context, "llm_exception")

    def build_event(
        self,
        *,
        run_id: str,
        event_type: str,
        state: RunState,
        message: AgentMessage,
        created_at: str,
    ) -> RunEvent:
        return self.fallback_runner.build_event(
            run_id=run_id,
            event_type=event_type,
            state=state,
            message=message,
            created_at=created_at,
        )

    def _fallback(
        self, role: str, context: dict[str, Any], reason: str
    ) -> AgentMessage:
        message = self.fallback_runner.run_role(role, context)
        self.execution_log[role] = {
            "source": "hard_fallback",
            "fallback_reason": reason,
            "recovery_reason": None,
        }
        self.debug_log[role] = {
            "status": "hard_fallback",
            "fallback_reason": reason,
            "recovery_reason": None,
            "raw_response": self.llm_runner.last_raw_response or "",
            "normalized_response": None,
            "usage": self.llm_runner.last_usage,
        }
        self.usage_events.append(
            {
                "component": f"role:{role}",
                "provider": self.llm_runner.provider,
                "model": self.llm_runner.model,
                "usage": dict(self.llm_runner.last_usage),
                "details": {"status": "hard_fallback", "fallback_reason": reason},
            }
        )
        return message

    def write_debug_artifacts(self, report_root: str | Path) -> None:
        for role, payload in self.debug_log.items():
            debug_path = write_llm_debug_artifact(
                report_root=report_root,
                name=role,
                payload=payload,
            )
            execution = self.execution_log.get(role, {})
            source = execution.get("source") or "deterministic"
            stage = _stage_for_role(role)
            append_onboarding_event(
                report_root=report_root,
                run_id="unknown",
                component="role_runner",
                stage=stage,
                event="llm_call_started",
                severity="info",
                summary="role llm call recorded",
                source="llm",
                details={"role": role},
            )
            if source in {"recovered_llm", "hard_fallback"}:
                append_generation_log(
                    report_root=report_root,
                    level="WARN",
                    component="role_runner",
                    event="recovery_started",
                    message="role payload recovery started",
                    details={
                        "role": role,
                        "source": source,
                        "recovery_reason": execution.get("recovery_reason"),
                        "hard_fallback_reason": execution.get("fallback_reason"),
                    },
                )
                append_generation_log(
                    report_root=report_root,
                    level="INFO" if source == "recovered_llm" else "WARN",
                    component="role_runner",
                    event="recovery_succeeded" if source == "recovered_llm" else "hard_fallback_used",
                    message="role payload recovered" if source == "recovered_llm" else "role payload used hard fallback",
                    details={
                        "role": role,
                        "source": source,
                        "recovery_reason": execution.get("recovery_reason"),
                        "hard_fallback_reason": execution.get("fallback_reason"),
                    },
                )
                append_onboarding_event(
                    report_root=report_root,
                    run_id="unknown",
                    component="role_runner",
                    stage=stage,
                    event="recovery_applied" if source == "recovered_llm" else "hard_fallback_used",
                    severity="info" if source == "recovered_llm" else "warn",
                    summary="role payload recovered" if source == "recovered_llm" else "role payload used hard fallback",
                    source=source,
                    recovery={
                        "applied": source == "recovered_llm",
                        "reason": execution.get("recovery_reason") if source == "recovered_llm" else execution.get("fallback_reason"),
                    },
                    details={"role": role},
                    debug_artifact_path=str(debug_path),
                )
            append_generation_log(
                report_root=report_root,
                level="INFO" if source == "llm" else "WARN",
                component="role_runner",
                event="role_completed",
                message="role execution recorded",
                details={
                    "role": role,
                    "source": source,
                    "fallback_reason": execution.get("fallback_reason") or "none",
                    "recovery_reason": execution.get("recovery_reason") or "none",
                    "debug_path": str(debug_path),
                },
            )
            append_onboarding_event(
                report_root=report_root,
                run_id="unknown",
                component="role_runner",
                stage=stage,
                event="artifact_written",
                severity="info",
                summary="role debug artifact written",
                source=source,
                details={"role": role, "artifact_kind": "llm_debug"},
                debug_artifact_path=str(debug_path),
            )
        for event in self.usage_events:
            append_llm_usage(
                report_root=report_root,
                component=str(event.get("component") or "role:unknown"),
                provider=event.get("provider"),
                model=event.get("model"),
                usage=event.get("usage") or {},
                details=event.get("details") or {},
            )


def build_llm_role_runner(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> LLMRoleRunner:
    return LLMRoleRunner(
        llm_factory=lambda: llm_builder(provider, model, 0),
        provider=provider,
        model=model,
    )


def _parse_json_payload(content: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    text = str(content).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    payload = json.loads(text)
    strict_error: ValidationError | None = None
    try:
        _validate_agent_payload(payload)
        return payload, {
            "recovery_applied": False,
            "recovery_reason": None,
            "normalized_payload": payload,
        }
    except ValidationError as exc:
        strict_error = exc

    normalized = _normalize_agent_payload(payload)
    _validate_agent_payload(normalized)
    return normalized, {
        "recovery_applied": True,
        "recovery_reason": "agent_payload_normalized",
        "normalized_payload": normalized,
        "validation_error": str(strict_error) if strict_error is not None else None,
    }


def _validate_agent_payload(payload: dict[str, Any]) -> None:
    AgentMessage(role="validation", **payload)


def _normalize_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)

    if "claim" in normalized:
        claim = normalized["claim"]
        normalized["claim"] = "" if claim is None else str(claim)

    if "evidence" in normalized:
        evidence = normalized["evidence"]
        if evidence is None:
            normalized["evidence"] = []
        elif isinstance(evidence, list):
            normalized["evidence"] = [
                str(item) for item in evidence if item is not None
            ]
        else:
            normalized["evidence"] = [str(evidence)]

    if "confidence" in normalized:
        confidence = normalized["confidence"]
        if isinstance(confidence, str):
            stripped = confidence.strip()
            match = re.search(r"[-+]?\d*\.?\d+", stripped)
            confidence = match.group(0) if match is not None else confidence.strip()
            if "%" in stripped:
                normalized["confidence"] = float(confidence) / 100
            else:
                normalized["confidence"] = float(confidence)
        else:
            normalized["confidence"] = float(confidence)

    if "risk" in normalized:
        risk = normalized["risk"]
        if isinstance(risk, list):
            normalized["risk"] = "; ".join(
                str(item).strip().lower() for item in risk if item is not None
            )
        else:
            normalized["risk"] = "" if risk is None else str(risk).strip().lower()

    if "next_action" in normalized:
        next_action = normalized["next_action"]
        if isinstance(next_action, list):
            normalized["next_action"] = "; ".join(
                str(item).strip() for item in next_action if item is not None
            )
        else:
            normalized["next_action"] = "" if next_action is None else str(next_action)

    if "blocking_issue" in normalized:
        blocking_issue = normalized["blocking_issue"]
        normalized["blocking_issue"] = (
            "" if blocking_issue is None else str(blocking_issue)
        )

    if "metadata" in normalized:
        metadata = normalized["metadata"]
        normalized["metadata"] = metadata if isinstance(metadata, dict) else {}

    return normalized


def _stage_for_role(role: str) -> str:
    mapping = {
        "Analyzer": "analysis",
        "Planner": "planning",
        "Generator": "generation",
        "Validator": "validation",
        "Diagnostician": "recovery",
    }
    return mapping.get(role, "unknown")
