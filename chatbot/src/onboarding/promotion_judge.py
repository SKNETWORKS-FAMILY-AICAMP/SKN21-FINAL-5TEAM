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
    ) -> dict[str, Any]:
        normalized_signature = str(failure_signature or "").strip()
        classification = classify_failure_signature(normalized_signature)
        site_local = is_site_local_failure_signature(normalized_signature)
        promote = bool(normalized_signature) and count >= self.threshold and not site_local
        return {
            "failure_signature": normalized_signature or None,
            "classification": classification,
            "count": count,
            "threshold": self.threshold,
            "site_local": site_local,
            "promote": promote,
            "repair_scope": "generator_promoted" if promote else current_scope,
            "reason": _build_reason(
                promote=promote,
                site_local=site_local,
                count=count,
                threshold=self.threshold,
            ),
        }


def _build_reason(*, promote: bool, site_local: bool, count: int, threshold: int) -> str:
    if promote:
        return "repeated_pipeline_failure"
    if site_local:
        return "site_local_signature"
    if count < threshold:
        return "below_promotion_threshold"
    return "promotion_not_applicable"
