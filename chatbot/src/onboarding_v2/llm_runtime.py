from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from chatbot.src.onboarding_v2.models import ArtifactRef, DebugRecord
from chatbot.src.onboarding_v2.stage_tools import StageToolRuntime
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
    tool_runtime: StageToolRuntime | None = None,
    max_tool_rounds: int = 3,
) -> ModelT:
    factory = llm_builder
    if factory is None:
        from chatbot.src.graph.llm_providers import make_chat_llm

        factory = make_chat_llm

    normalized: ModelT
    response_payload: dict[str, Any]
    parse_result: dict[str, Any]
    token_usage: dict[str, Any] = {}
    tool_trace: list[dict[str, Any]] = []
    try:
        if llm_builder is None and not _llm_enabled_by_default(provider):
            raise RuntimeError(f"{provider} llm disabled for onboarding_v2 stage execution")
        llm = factory(provider, model, 0)
        response, tool_trace, token_usage = _invoke_with_optional_tools(
            llm=llm,
            system_prompt=system_prompt,
            payload=payload,
            tool_runtime=tool_runtime,
            max_tool_rounds=max_tool_rounds,
        )
        raw_content = _extract_response_content(response)
        response_payload = {"content": raw_content, "tool_trace": tool_trace}
        normalized = response_model.model_validate(_parse_json(raw_content))
        parse_result = {"status": "parsed", "owner": "llm"}
    except Exception as exc:
        normalized = response_model.model_validate(fallback_payload)
        response_payload = {"error": str(exc), "tool_trace": tool_trace}
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
            extra={
                "status": parse_result["status"],
                "tool_call_count": len(tool_trace),
                "tool_names": [entry["tool_name"] for entry in tool_trace],
            },
        )
    return normalized


def _invoke_with_optional_tools(
    *,
    llm: Any,
    system_prompt: str,
    payload: dict[str, Any],
    tool_runtime: StageToolRuntime | None,
    max_tool_rounds: int,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
    ]
    tool_trace: list[dict[str, Any]] = []
    token_usage: dict[str, Any] = {}

    bound_llm = _bind_tools_if_supported(llm=llm, tool_runtime=tool_runtime)
    if bound_llm is None:
        response = llm.invoke(messages)
        return response, tool_trace, _merge_token_usage(token_usage, _extract_token_usage(response))

    tool_rounds = 0
    while True:
        response = bound_llm.invoke(messages)
        token_usage = _merge_token_usage(token_usage, _extract_token_usage(response))
        messages.append(response)
        tool_calls = _extract_tool_calls(response)
        if not tool_calls:
            return response, tool_trace, token_usage
        if tool_rounds >= max_tool_rounds:
            raise RuntimeError(f"tool round limit exceeded for {tool_runtime.stage if tool_runtime else 'stage'}")
        for tool_call in tool_calls:
            tool_message, trace_entry = _execute_tool_call(tool_runtime=tool_runtime, tool_call=tool_call)
            tool_trace.append(trace_entry)
            messages.append(tool_message)
        tool_rounds += 1


def _bind_tools_if_supported(*, llm: Any, tool_runtime: StageToolRuntime | None) -> Any | None:
    if tool_runtime is None or not tool_runtime.tools:
        return None
    bind_tools = getattr(llm, "bind_tools", None)
    if not callable(bind_tools):
        return None
    try:
        return bind_tools(tool_runtime.tools)
    except Exception:
        return None


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(response, "tool_calls", None) or []
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        normalized.append(call)
    return normalized


def _execute_tool_call(
    *,
    tool_runtime: StageToolRuntime | None,
    tool_call: dict[str, Any],
) -> tuple[ToolMessage, dict[str, Any]]:
    tool_name = str(tool_call.get("name") or "").strip()
    tool_call_id = str(tool_call.get("id") or tool_name or "tool-call").strip()
    raw_args = tool_call.get("args")
    if raw_args is None:
        args: Any = {}
    else:
        args = raw_args
    available_tools = {tool.name: tool for tool in (tool_runtime.tools if tool_runtime is not None else [])}
    result: dict[str, Any]
    status = "success"
    tool = available_tools.get(tool_name)
    if tool is None:
        status = "error"
        result = {
            "error": "tool_not_available",
            "tool_name": tool_name,
        }
    else:
        try:
            tool_output = tool.invoke(args)
            if isinstance(tool_output, dict):
                result = tool_output
            else:
                result = {"result": tool_output}
        except Exception as exc:
            status = "error"
            result = {
                "error": "tool_execution_failed",
                "tool_name": tool_name,
                "details": str(exc),
            }
    trace_entry = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "args": args if isinstance(args, dict) else {"value": args},
        "status": status,
        "result": result,
    }
    return (
        ToolMessage(
            content=json.dumps(result, ensure_ascii=False),
            tool_call_id=tool_call_id,
            name=tool_name or None,
            status=status,
        ),
        trace_entry,
    )


def _merge_token_usage(current: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    if not current:
        if not latest:
            return {}
        merged = dict(latest)
        raw_value = merged.get("raw")
        if raw_value is not None and not isinstance(raw_value, list):
            merged["raw"] = [raw_value]
        return merged
    if not latest:
        return current

    merged = {
        "input_tokens": int(current.get("input_tokens") or 0) + int(latest.get("input_tokens") or 0),
        "output_tokens": int(current.get("output_tokens") or 0) + int(latest.get("output_tokens") or 0),
        "cached_input_tokens": int(current.get("cached_input_tokens") or 0)
        + int(latest.get("cached_input_tokens") or 0),
        "total_tokens": int(current.get("total_tokens") or 0) + int(latest.get("total_tokens") or 0),
    }
    raw_entries: list[Any] = []
    for value in (current.get("raw"), latest.get("raw")):
        if value is None:
            continue
        if isinstance(value, list):
            raw_entries.extend(value)
        else:
            raw_entries.append(value)
    if raw_entries:
        merged["raw"] = raw_entries
    return merged


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
    metadata = getattr(response, "response_metadata", None) or {}
    metadata_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    input_details = usage.get("input_token_details") or usage.get("prompt_tokens_details") or {}
    metadata_input_details = metadata_usage.get("prompt_tokens_details") or {}

    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or metadata_usage.get("prompt_tokens") or 0)
    output_tokens = int(
        usage.get("output_tokens") or usage.get("completion_tokens") or metadata_usage.get("completion_tokens") or 0
    )
    cached_input_tokens = int(
        usage.get("cached_input_tokens")
        or input_details.get("cached_tokens")
        or input_details.get("cache_read")
        or metadata_input_details.get("cached_tokens")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or metadata_usage.get("total_tokens") or (input_tokens + output_tokens))
    if not usage and not total_tokens:
        return {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "total_tokens": total_tokens,
        "raw": usage or metadata_usage,
    }
