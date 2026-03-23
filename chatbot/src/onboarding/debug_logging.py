from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chatbot.src.core.config import settings


KNOWN_MODEL_PRICING = {
    "gpt-4o-mini": {
        "input_cost_per_1m": 0.15,
        "output_cost_per_1m": 0.60,
        "cached_input_cost_per_1m": 0.075,
        "pricing_source": "openai_public_pricing_2026-03-16",
    },
    "gpt-4.1-mini": {
        "input_cost_per_1m": 0.40,
        "output_cost_per_1m": 1.60,
        "cached_input_cost_per_1m": 0.10,
        "pricing_source": "openai_public_pricing_2026-03-16",
    },
    "gpt-5-mini": {
        "input_cost_per_1m": 0.25,
        "output_cost_per_1m": 2.00,
        "cached_input_cost_per_1m": 0.025,
        "pricing_source": "openai_public_pricing_2026-03-16",
    },
}


def append_onboarding_event(
    *,
    report_root: str | Path,
    run_id: str,
    component: str,
    stage: str,
    event: str,
    severity: str,
    summary: str,
    source: str | None = None,
    details: dict[str, Any] | None = None,
    related_files: list[str] | None = None,
    recovery: dict[str, Any] | None = None,
    llm_usage: dict[str, Any] | None = None,
    next_action: str | None = None,
    debug_artifact_path: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Path]:
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    generation_log_path = reports / "generation.log"
    event_log_path = reports / "execution-trace.jsonl"
    pretty_event_log_path = reports / "execution-trace.json"

    payload = _normalize_onboarding_event(
        run_id=run_id,
        component=component,
        stage=stage,
        event=event,
        severity=severity,
        summary=summary,
        source=source,
        details=details,
        related_files=related_files,
        recovery=recovery,
        llm_usage=llm_usage,
        next_action=next_action,
        debug_artifact_path=debug_artifact_path,
        timestamp=timestamp,
    )

    with generation_log_path.open("a", encoding="utf-8") as fp:
        fp.write(_render_onboarding_event_line(payload) + "\n")
    with event_log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    pretty_payload: list[dict[str, Any]] = []
    if pretty_event_log_path.exists():
        pretty_payload = json.loads(pretty_event_log_path.read_text(encoding="utf-8"))
    pretty_payload.append(payload)
    pretty_event_log_path.write_text(
        json.dumps(pretty_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "generation_log_path": generation_log_path,
        "event_log_path": event_log_path,
    }


def append_execution_trace(
    *,
    report_root: str | Path,
    event: str,
    status: str,
    run_id: str,
    related_files: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> Path:
    paths = append_onboarding_event(
        report_root=report_root,
        run_id=run_id,
        component=str((details or {}).get("component") or "orchestrator"),
        stage=str((details or {}).get("stage") or _infer_stage_from_event(event)),
        event=event,
        severity=_severity_from_status(status),
        summary=str((details or {}).get("summary") or event.replace("_", " ")),
        source=(details or {}).get("source"),
        details=details,
        related_files=related_files,
    )
    return paths["event_log_path"]


def update_file_activity(
    *,
    report_root: str | Path,
    file_path: str,
    activity_type: str,
    activity_value: str,
) -> Path:
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "file-activity.json"
    payload: dict[str, dict[str, list[str]]] = {}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault(file_path, {})
    payload[file_path].setdefault(activity_type, [])
    if activity_value not in payload[file_path][activity_type]:
        payload[file_path][activity_type].append(activity_value)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_llm_debug_artifact(
    *,
    report_root: str | Path,
    name: str,
    payload: dict[str, Any],
) -> Path:
    debug_root = Path(report_root) / "llm-debug"
    debug_root.mkdir(parents=True, exist_ok=True)
    path = debug_root / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_generation_log(
    *,
    report_root: str | Path,
    level: str,
    component: str,
    event: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> Path:
    paths = append_onboarding_event(
        report_root=report_root,
        run_id=str((details or {}).get("run_id") or "unknown"),
        component=component,
        stage=str((details or {}).get("stage") or _infer_stage_from_event(event)),
        event=event,
        severity=level.lower(),
        summary=message,
        source=(details or {}).get("source"),
        details=details,
        related_files=(details or {}).get("related_files"),
        debug_artifact_path=(details or {}).get("debug_path"),
    )
    return paths["generation_log_path"]


def append_recovery_event(
    *,
    report_root: str | Path,
    component: str,
    source: str,
    recovery_reason: str | None = None,
    hard_fallback_reason: str | None = None,
) -> Path:
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "recovery-events.json"
    payload: list[dict[str, Any]] = []
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload.append(
        {
            "component": component,
            "source": source,
            "recovery_reason": recovery_reason,
            "hard_fallback_reason": hard_fallback_reason,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component=component,
        stage="recovery",
        event="recovery_applied" if source == "recovered_llm" else "hard_fallback_used",
        severity="info" if source == "recovered_llm" else "warn",
        summary="recovery applied" if source == "recovered_llm" else "hard fallback used",
        source=source,
        recovery={
            "applied": source == "recovered_llm",
            "reason": recovery_reason if source == "recovered_llm" else hard_fallback_reason,
        },
        details={
            "recovery_reason": recovery_reason,
            "hard_fallback_reason": hard_fallback_reason,
        },
    )
    return path


def extract_llm_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}
    input_details = usage.get("input_token_details") or usage.get("prompt_tokens_details") or {}
    response_input_details = token_usage.get("prompt_tokens_details") or {}

    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or token_usage.get("prompt_tokens") or 0)
    output_tokens = int(
        usage.get("output_tokens") or usage.get("completion_tokens") or token_usage.get("completion_tokens") or 0
    )
    cached_input_tokens = int(
        usage.get("cached_input_tokens")
        or input_details.get("cached_tokens")
        or input_details.get("cache_read")
        or response_input_details.get("cached_tokens")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or token_usage.get("total_tokens") or (input_tokens + output_tokens))

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "total_tokens": total_tokens,
    }


def append_llm_usage(
    *,
    report_root: str | Path,
    component: str,
    usage: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
    details: dict[str, Any] | None = None,
) -> Path:
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "llm-usage.json"
    pricing = _resolve_pricing(provider=provider, model=model)
    payload = {
        "totals": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "total_tokens": 0,
            "estimated_input_cost_usd": 0.0,
            "estimated_output_cost_usd": 0.0,
            "estimated_cached_input_cost_usd": 0.0,
            "estimated_total_cost_usd": 0.0,
        },
        "pricing": pricing,
        "calls": [],
    }
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))

    normalized = {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    estimated = _estimate_llm_usage_cost(normalized, pricing=pricing)
    call = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "provider": provider or "unknown",
        "model": model or "unknown",
        **normalized,
        **estimated,
        "details": details or {},
    }
    payload["calls"].append(call)

    totals = payload["totals"]
    totals["input_tokens"] += normalized["input_tokens"]
    totals["output_tokens"] += normalized["output_tokens"]
    totals["cached_input_tokens"] += normalized["cached_input_tokens"]
    totals["total_tokens"] += normalized["total_tokens"]
    totals["estimated_input_cost_usd"] += estimated["estimated_input_cost_usd"]
    totals["estimated_output_cost_usd"] += estimated["estimated_output_cost_usd"]
    totals["estimated_cached_input_cost_usd"] += estimated["estimated_cached_input_cost_usd"]
    totals["estimated_total_cost_usd"] += estimated["estimated_total_cost_usd"]

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def _estimate_llm_usage_cost(
    usage: dict[str, int],
    *,
    pricing: dict[str, Any],
) -> dict[str, float]:
    cached_input_tokens = int(usage.get("cached_input_tokens") or 0)
    input_tokens = int(usage.get("input_tokens") or 0)
    uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    output_tokens = int(usage.get("output_tokens") or 0)

    input_cost = (uncached_input_tokens / 1_000_000) * float(pricing.get("input_cost_per_1m") or 0.0)
    output_cost = (output_tokens / 1_000_000) * float(pricing.get("output_cost_per_1m") or 0.0)
    cached_input_cost = (cached_input_tokens / 1_000_000) * float(pricing.get("cached_input_cost_per_1m") or 0.0)

    return {
        "estimated_input_cost_usd": round(input_cost, 8),
        "estimated_output_cost_usd": round(output_cost, 8),
        "estimated_cached_input_cost_usd": round(cached_input_cost, 8),
        "estimated_total_cost_usd": round(input_cost + output_cost + cached_input_cost, 8),
    }


def _resolve_pricing(*, provider: str | None, model: str | None) -> dict[str, Any]:
    configured = {
        "input_cost_per_1m": settings.ONBOARDING_LLM_INPUT_COST_PER_1M,
        "output_cost_per_1m": settings.ONBOARDING_LLM_OUTPUT_COST_PER_1M,
        "cached_input_cost_per_1m": settings.ONBOARDING_LLM_CACHED_INPUT_COST_PER_1M,
        "pricing_source": "configured",
    }
    if any(value > 0 for key, value in configured.items() if key.endswith("_per_1m")):
        return configured

    normalized_model = (model or "").strip()
    for candidate, pricing in KNOWN_MODEL_PRICING.items():
        if normalized_model == candidate or normalized_model.startswith(f"{candidate}-"):
            return pricing

    return {
        "input_cost_per_1m": 0.0,
        "output_cost_per_1m": 0.0,
        "cached_input_cost_per_1m": 0.0,
        "pricing_source": f"unknown:{provider or 'unknown'}:{normalized_model or 'unknown'}",
    }


def _format_generation_details(details: dict[str, Any] | None) -> str:
    if not details:
        return ""

    parts: list[str] = []
    for key, value in details.items():
        if value is None:
            continue
        normalized = str(value).replace("\n", "\\n")
        if any(ch.isspace() for ch in normalized):
            normalized = json.dumps(normalized, ensure_ascii=False)
        parts.append(f"{key}={normalized}")
    return " ".join(parts)


def _normalize_onboarding_event(
    *,
    run_id: str,
    component: str,
    stage: str,
    event: str,
    severity: str,
    summary: str,
    source: str | None,
    details: dict[str, Any] | None,
    related_files: list[str] | None,
    recovery: dict[str, Any] | None,
    llm_usage: dict[str, Any] | None,
    next_action: str | None,
    debug_artifact_path: str | None,
    timestamp: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "component": component,
        "stage": stage,
        "event": event,
        "severity": severity.lower(),
        "summary": summary,
    }
    if source is not None:
        payload["source"] = source
    if details:
        payload["details"] = details
    if related_files:
        payload["related_files"] = related_files
    if recovery:
        payload["recovery"] = recovery
    if llm_usage:
        payload["llm_usage"] = llm_usage
    if next_action:
        payload["next_action"] = next_action
    if debug_artifact_path:
        payload["debug_artifact_path"] = debug_artifact_path
    return payload


def _render_onboarding_event_line(payload: dict[str, Any]) -> str:
    rendered_details = _format_generation_details(_build_line_details(payload))
    return " ".join(
        item
        for item in [
            str(payload["timestamp"]),
            str(payload["severity"]).upper(),
            str(payload["component"]),
            str(payload["event"]),
            str(payload["summary"]),
            rendered_details,
        ]
        if item
    )


def _build_line_details(payload: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {"stage": payload.get("stage")}
    if payload.get("source") is not None:
        details["source"] = payload.get("source")
    if payload.get("debug_artifact_path") is not None:
        details["debug_artifact_path"] = payload.get("debug_artifact_path")
    if payload.get("next_action") is not None:
        details["next_action"] = payload.get("next_action")
    recovery = payload.get("recovery") or {}
    if recovery.get("reason") is not None:
        details["recovery_reason"] = recovery.get("reason")
    event_details = payload.get("details") or {}
    details.update(event_details)
    return details


def _infer_stage_from_event(event: str) -> str:
    normalized = event.lower()
    for stage in ("analysis", "planning", "generation", "validation", "export", "recovery", "simulation"):
        if stage in normalized:
            return stage
    return "unknown"


def _severity_from_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"failed", "error"}:
        return "error"
    if normalized in {"warning", "warn"}:
        return "warn"
    return "info"
