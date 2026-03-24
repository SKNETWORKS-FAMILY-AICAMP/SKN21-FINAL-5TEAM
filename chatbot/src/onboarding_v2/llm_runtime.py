from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from chatbot.src.onboarding_v2.models import ArtifactRef, DebugRecord
from chatbot.src.onboarding_v2.storage import DebugStore, LlmUsageStore

ModelT = TypeVar("ModelT", bound=BaseModel)


def invoke_structured_stage(
    *,
    stage: str,
    phase: str,
    provider: str,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    response_model: type[ModelT],
    fallback_payload: dict[str, Any],
    attempt: int = 1,
    debug_store: DebugStore | None = None,
    usage_store: LlmUsageStore | None = None,
    llm_builder: Callable[[str, str, float], Any] | None = None,
    artifact_refs: list[ArtifactRef] | None = None,
) -> ModelT:
    factory = llm_builder
    if factory is None:
        from chatbot.src.graph.llm_providers import make_chat_llm

        factory = make_chat_llm

    normalized: ModelT
    response_payload: dict[str, Any]
    parse_result: dict[str, Any]
    token_usage: dict[str, Any] = {}
    try:
        if llm_builder is None and not _llm_enabled_by_default(provider):
            raise RuntimeError(f"{provider} llm disabled for onboarding_v2 stage execution")
        llm = factory(provider, model, 0)
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
            ]
        )
        raw_content = _extract_response_content(response)
        response_payload = {"content": raw_content}
        token_usage = _extract_token_usage(response)
        normalized = response_model.model_validate(_parse_json(raw_content))
        parse_result = {"status": "parsed", "owner": "llm"}
    except Exception as exc:
        normalized = response_model.model_validate(fallback_payload)
        response_payload = {"error": str(exc)}
        parse_result = {"status": "fallback", "owner": "deterministic", "error": str(exc)}

    if debug_store is not None:
        debug_store.write_record(
            stage=stage,
            label=phase,
            record=DebugRecord(
                stage=stage,
                attempt=attempt,
                prompt=payload,
                response=response_payload,
                normalized_response=normalized.model_dump(mode="json"),
                parse_result=parse_result,
                token_usage=token_usage,
                artifact_refs=list(artifact_refs or []),
            ),
        )
    if usage_store is not None:
        usage_store.append(
            stage=stage,
            phase=phase,
            attempt=attempt,
            provider=provider,
            model=model,
            usage=token_usage,
            extra={"status": parse_result["status"]},
        )
    return normalized


def _llm_enabled_by_default(provider: str) -> bool:
    if os.getenv("ONBOARDING_V2_ENABLE_LLM", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    return _has_provider_credentials(provider)


def _has_provider_credentials(provider: str) -> bool:
    normalized = str(provider or "").strip().lower()
    if normalized in {"openai", ""}:
        return bool(os.getenv("OPENAI_API_KEY"))
    if normalized == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if normalized == "ollama":
        return True
    return False


def _extract_response_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def _parse_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _extract_token_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        metadata = getattr(response, "response_metadata", None) or {}
        usage = metadata.get("token_usage") or metadata.get("usage") or {}

    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    if not usage and not total_tokens:
        return {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "raw": usage,
    }
