from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chatbot.src.core.config import settings
from chatbot.src.onboarding.debug_logging import KNOWN_MODEL_PRICING


class LlmUsageStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.path = self.run_root / "debug" / "llm-usage.jsonl"
        self.summary_path = self.run_root / "debug" / "llm-usage-summary.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        stage: str,
        phase: str,
        attempt: int,
        provider: str,
        model: str,
        usage: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Path:
        normalized_usage = _normalize_usage(usage)
        pricing = _resolve_pricing(provider=provider, model=model)
        estimated = _estimate_llm_usage_cost(normalized_usage, pricing=pricing)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "phase": phase,
            "attempt": attempt,
            "provider": provider,
            "model": model,
            "usage": normalized_usage,
            "pricing": pricing,
            "estimated": estimated,
            "extra": dict(extra or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._write_summary(
            call={
                "timestamp": record["timestamp"],
                "stage": stage,
                "phase": phase,
                "attempt": attempt,
                "provider": provider or "unknown",
                "model": model or "unknown",
                **normalized_usage,
                **estimated,
                "pricing": pricing,
                "details": dict(extra or {}),
            },
            pricing=pricing,
        )
        return self.path

    def read_summary(self) -> dict[str, Any] | None:
        if not self.summary_path.exists():
            return None
        return json.loads(self.summary_path.read_text(encoding="utf-8"))

    def _write_summary(self, *, call: dict[str, Any], pricing: dict[str, Any]) -> None:
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
        if self.summary_path.exists():
            payload = json.loads(self.summary_path.read_text(encoding="utf-8"))

        payload["calls"].append(call)
        payload["pricing"] = _merge_summary_pricing(payload.get("pricing"), pricing)

        totals = payload["totals"]
        totals["input_tokens"] += int(call.get("input_tokens") or 0)
        totals["output_tokens"] += int(call.get("output_tokens") or 0)
        totals["cached_input_tokens"] += int(call.get("cached_input_tokens") or 0)
        totals["total_tokens"] += int(call.get("total_tokens") or 0)
        totals["estimated_input_cost_usd"] += float(call.get("estimated_input_cost_usd") or 0.0)
        totals["estimated_output_cost_usd"] += float(call.get("estimated_output_cost_usd") or 0.0)
        totals["estimated_cached_input_cost_usd"] += float(
            call.get("estimated_cached_input_cost_usd") or 0.0
        )
        totals["estimated_total_cost_usd"] += float(call.get("estimated_total_cost_usd") or 0.0)

        for key in (
            "estimated_input_cost_usd",
            "estimated_output_cost_usd",
            "estimated_cached_input_cost_usd",
            "estimated_total_cost_usd",
        ):
            totals[key] = round(float(totals.get(key) or 0.0), 8)

        self.summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(usage or {})
    input_tokens = int(normalized.get("input_tokens") or 0)
    output_tokens = int(normalized.get("output_tokens") or 0)
    cached_input_tokens = int(normalized.get("cached_input_tokens") or 0)
    total_tokens = int(normalized.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "total_tokens": total_tokens,
    }


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
    for candidate, candidate_pricing in KNOWN_MODEL_PRICING.items():
        if normalized_model == candidate or normalized_model.startswith(f"{candidate}-"):
            return dict(candidate_pricing)

    return {
        "input_cost_per_1m": 0.0,
        "output_cost_per_1m": 0.0,
        "cached_input_cost_per_1m": 0.0,
        "pricing_source": f"unknown:{provider or 'unknown'}:{normalized_model or 'unknown'}",
    }


def _merge_summary_pricing(current: Any, latest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(current, dict) or not current:
        return dict(latest)
    if current == latest:
        return current
    return {
        "pricing_source": "mixed_per_call",
    }
