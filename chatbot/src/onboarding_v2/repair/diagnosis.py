from __future__ import annotations

import json
import re
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from chatbot.src.onboarding_v2.models.common import DebugRecord
from chatbot.src.onboarding_v2.models.repair import FailureBundle, RepairDecision
from chatbot.src.onboarding_v2.repair.llm import build_repair_llm_factory
from chatbot.src.onboarding_v2.storage import DebugStore

_REPAIR_SYSTEM_PROMPT = """You are the RepairAgent diagnose phase for the onboarding_v2 pipeline.
Return only JSON with these keys:
- failure_signature
- diagnosis
- rewind_to
- preserve_artifacts
- required_rechecks
- additional_discovery
- artifact_overrides
- stop
- stop_reason

Rules:
- rewind_to must be one of: validation, compile, planning, analysis.
- preserve_artifacts must contain only stage names.
- additional_discovery must be an array of objects with keys path and reason.
- artifact_overrides must be a JSON object.
- If the failure can be retried without changing strategy, prefer validation.
- If strategy or target changes are required, use planning or analysis.
- If you cannot diagnose safely, set stop=true and stop_reason to a short machine-friendly reason.
Do not include markdown."""


def diagnose_failure(
    *,
    failure_bundle: FailureBundle,
    snapshot_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    edit_program_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    llm_provider: str,
    llm_model: str,
    debug_store: DebugStore,
    llm_factory: Callable[[], Any] | None = None,
) -> RepairDecision:
    payload = {
        "failure_bundle": failure_bundle.model_dump(mode="json"),
        "snapshot": snapshot_payload,
        "plan": plan_payload,
        "edit_program": edit_program_payload,
        "validation": validation_payload,
    }
    factory = llm_factory or build_repair_llm_factory(provider=llm_provider, model=llm_model)
    try:
        llm = factory()
        response = llm.invoke(
            [
                SystemMessage(content=_REPAIR_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
            ]
        )
        parsed = _parse_response(response.content)
        decision = RepairDecision.model_validate(parsed)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"content": str(response.content)},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "parsed"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    except Exception as exc:
        decision = RepairDecision(
            failure_signature=failure_bundle.failure_signature,
            diagnosis="repair llm unavailable",
            rewind_to="validation",
            preserve_artifacts=[],
            required_rechecks=[],
            additional_discovery=[],
            artifact_overrides={},
            stop=True,
            stop_reason="repair_llm_unavailable",
        )
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"error": str(exc)},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "fallback", "error": str(exc)},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision


def _parse_response(raw: Any) -> dict[str, Any]:
    text = str(raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))
