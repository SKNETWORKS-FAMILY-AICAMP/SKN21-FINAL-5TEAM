from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .recovery_planner import classify_failure_signature, is_site_local_failure_signature


@dataclass(frozen=True)
class PromotionJudge:
    threshold: int = 2

    def decide(
        self,
        *,
        failure_signature: str | None,
        count: int,
        current_scope: str = "run_only",
        recommendation_scope: str | None = None,
    ) -> dict[str, Any]:
        normalized_signature = str(failure_signature or "").strip()
        classification = classify_failure_signature(normalized_signature)
        site_local = is_site_local_failure_signature(normalized_signature)
        normalized_recommendation = str(recommendation_scope or "").strip()
        if normalized_recommendation not in {"run_only", "generator_promoted"}:
            normalized_recommendation = "generator_promoted" if current_scope == "generator_promoted" else ""
        recommended_scope = normalized_recommendation or current_scope
        recommend_promotion = recommended_scope == "generator_promoted"
        promote = (
            bool(normalized_signature)
            and recommend_promotion
            and count >= self.threshold
            and not site_local
        )
        return {
            "failure_signature": normalized_signature or None,
            "classification": classification,
            "count": count,
            "threshold": self.threshold,
            "site_local": site_local,
            "promote": promote,
            "recommended_scope": recommended_scope,
            "repair_scope": "generator_promoted" if promote else current_scope,
            "reason": _build_reason(
                promote=promote,
                recommend_promotion=recommend_promotion,
                site_local=site_local,
                count=count,
                threshold=self.threshold,
            ),
        }


def _build_reason(*, promote: bool, recommend_promotion: bool, site_local: bool, count: int, threshold: int) -> str:
    if promote:
        return "repeated_pipeline_failure"
    if not recommend_promotion:
        return "llm_recommended_run_only"
    if site_local:
        return "site_local_signature"
    if count < threshold:
        return "below_promotion_threshold"
    return "promotion_not_applicable"
