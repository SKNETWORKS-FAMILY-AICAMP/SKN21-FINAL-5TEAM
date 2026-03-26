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
- Compile-stage failures that mention compile-preflight, banned imports, server_fastapi import failures, or chatbot_runtime_import* are import-graph defects. Prefer rewind_to=compile with required_rechecks including compile_preflight.
- If strategy or target changes are required, use planning or analysis.
- If you cannot diagnose safely, set stop=true and stop_reason to a short machine-friendly reason.
Do not include markdown."""


def _is_compile_import_graph_failure(failure_bundle: FailureBundle) -> bool:
    if failure_bundle.failed_stage != "compile":
        return False
    artifact_types = {artifact.artifact_type for artifact in failure_bundle.related_artifacts}
    haystack = (
        f"{failure_bundle.failure_signature}\n"
        f"{failure_bundle.failure_summary}"
    ).lower()
    if "compile-preflight" in artifact_types:
        return True
    return "chatbot_runtime_import" in haystack or "banned import" in haystack


def _build_compile_import_graph_decision(failure_bundle: FailureBundle) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "compile import-graph defect detected from compile preflight; "
            "rewind to compile and rerun compile_preflight"
        ),
        rewind_to="compile",
        preserve_artifacts=["analysis", "planning"],
        required_rechecks=["compile_preflight"],
        additional_discovery=[],
        artifact_overrides={},
        stop=False,
        stop_reason=None,
    )


def _is_host_auth_bootstrap_failure(failure_bundle: FailureBundle) -> bool:
    if failure_bundle.failed_stage != "validation":
        return False
    haystack = (
        f"{failure_bundle.failure_signature}\n"
        f"{failure_bundle.failure_summary}"
    ).lower()
    tokens = (
        "host_auth_bootstrap",
        "host login failed",
        "bootstrap contract",
        "bootstrap missing",
        "missing site_id",
        "missing user.id",
        "missing access_token",
        "missing authenticated=true",
    )
    return any(token in haystack for token in tokens)


def _build_host_auth_bootstrap_decision(failure_bundle: FailureBundle) -> RepairDecision:
    return RepairDecision(
        failure_signature=failure_bundle.failure_signature,
        diagnosis=(
            "host auth bootstrap contract/login failure detected during validation; "
            "rerun validation and recheck host_auth_bootstrap before considering compile changes"
        ),
        rewind_to="validation",
        preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
        required_rechecks=["host_auth_bootstrap"],
        additional_discovery=[],
        artifact_overrides={},
        stop=False,
        stop_reason=None,
    )


def diagnose_failure(
    *,
    failure_bundle: FailureBundle,
    analysis_bundle_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
    planning_bundle_payload: dict[str, Any],
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
        "analysis_bundle": analysis_bundle_payload,
        "snapshot": snapshot_payload,
        "planning_bundle": planning_bundle_payload,
        "plan": plan_payload,
        "edit_program": edit_program_payload,
        "validation": validation_payload,
    }
    if _is_compile_import_graph_failure(failure_bundle):
        decision = _build_compile_import_graph_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "compile_import_graph_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
    if _is_host_auth_bootstrap_failure(failure_bundle):
        decision = _build_host_auth_bootstrap_decision(failure_bundle)
        debug_store.write_record(
            stage="repair",
            record=DebugRecord(
                stage="repair",
                prompt=payload,
                response={"heuristic": "host_auth_bootstrap_failure"},
                normalized_response=decision.model_dump(mode="json"),
                parse_result={"status": "heuristic"},
                artifact_refs=failure_bundle.related_artifacts,
            ),
        )
        return decision
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
