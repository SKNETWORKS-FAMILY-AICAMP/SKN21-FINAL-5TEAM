from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from chatbot.src.graph.llm_providers import make_chat_llm

from .agent_contracts import AgentMessage, RunEvent, RunState


SUPPORTED_ROLES = {
    "Analyzer",
    "Planner",
    "Generator",
    "Validator",
    "Diagnostician",
}


@dataclass
class RoleRunner:
    responders: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = field(default_factory=dict)

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

Your job:
- Use the analysis output to decide which capabilities should be implemented first.
- Be explicit about missing_capabilities and risks before generation.
- Prioritize auth.chat_token_issue and orders/catalog capabilities before frontend polish when those are missing.
- Do not invent routes, capabilities, or implementation status.
- Do not propose deployment, direct production edits, or bypassing runtime copy / approval gates.

metadata must be an object and should include:
- priority_capabilities: array
- missing_capabilities: array
- recommended_outputs: array
- approval_risks: array

Use the term capabilities explicitly in your reasoning.
Mention runtime copy when discussing execution safety.
""",
    "Generator": """You are the Generator role for a website onboarding agent.
Return only JSON with keys: claim, evidence, confidence, risk, next_action, blocking_issue, metadata.
Do not add markdown.

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

Your job:
- Read the failure_signature, retry budget, and validation evidence.
- Produce a root_cause_hypothesis and proposed_fix.
- Decide conservatively whether retry is justified.
- Treat missing scripts, missing patch targets, and hard auth mismatches as structural failures that should not retry.
- Use retry budget explicitly; if budget is exhausted, do not recommend retry.

metadata must be an object and should include:
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
        payload = _parse_json_payload(response.content)
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


def build_llm_role_runner(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> LLMRoleRunner:
    return LLMRoleRunner(
        llm_factory=lambda: llm_builder(provider, model, 0),
    )


def _parse_json_payload(content: Any) -> dict[str, Any]:
    text = str(content).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)
