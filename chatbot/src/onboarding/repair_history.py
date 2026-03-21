from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run_repair_history_path(run_root: str | Path) -> Path:
    return Path(run_root) / "reports" / "repair-history.json"


def site_repair_history_path(generated_root: str | Path, site: str) -> Path:
    return Path(generated_root) / site / "repair-history.json"


def read_failure_count(*, generated_root: str | Path, site: str, failure_signature: str | None) -> int:
    normalized_signature = str(failure_signature or "").strip()
    if not normalized_signature:
        return 0
    site_payload = _read_json(site_repair_history_path(generated_root, site))
    signatures = site_payload.get("signatures") or {}
    if not isinstance(signatures, dict):
        return 0
    signature_payload = signatures.get(normalized_signature) or {}
    try:
        return int(signature_payload.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def write_repair_history(
    *,
    generated_root: str | Path,
    run_root: str | Path,
    site: str,
    run_id: str,
    failure_signature: str | None,
    repair_scope: str = "run_only",
    files_touched: list[str] | None = None,
    evaluation_delta: dict[str, Any] | None = None,
    promotion_decision: dict[str, Any] | None = None,
    repair_recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_history_path = run_repair_history_path(run_root)
    site_history_path = site_repair_history_path(generated_root, site)
    run_history_path.parent.mkdir(parents=True, exist_ok=True)
    site_history_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_signature = str(failure_signature or "").strip()
    site_payload = _read_json(site_history_path) or {"site": site, "signatures": {}}
    signatures = site_payload.setdefault("signatures", {})
    count = 0
    if normalized_signature:
        signature_payload = signatures.setdefault(
            normalized_signature,
            {
                "count": 0,
                "last_run_id": None,
                "last_repair_scope": None,
                "last_recommendation_scope": None,
            },
        )
        previous_run_id = str(signature_payload.get("last_run_id") or "").strip()
        current_count = int(signature_payload.get("count") or 0)
        if previous_run_id != run_id:
            current_count += 1
        signature_payload["count"] = current_count
        signature_payload["last_run_id"] = run_id
        signature_payload["last_repair_scope"] = repair_scope
        recommendation_scope = str((repair_recommendation or {}).get("repair_scope") or "").strip()
        if recommendation_scope:
            signature_payload["last_recommendation_scope"] = recommendation_scope
        count = int(signature_payload["count"])

    site_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    site_history_path.write_text(
        json.dumps(site_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_payload = {
        "site": site,
        "run_id": run_id,
        "failure_signature": normalized_signature or None,
        "failure_count_for_signature": count if normalized_signature else 0,
        "repair_scope": repair_scope,
        "files_touched": files_touched or [],
        "evaluation_delta": evaluation_delta or {},
        "repair_recommendation": repair_recommendation or {},
        "promotion_decision": promotion_decision or {},
        "site_repair_history_path": str(site_history_path),
        "updated_at": site_payload["updated_at"],
    }
    run_history_path.write_text(
        json.dumps(run_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "repair_history_path": str(run_history_path),
        "site_repair_history_path": str(site_history_path),
        "failure_signature": run_payload["failure_signature"],
        "failure_count_for_signature": run_payload["failure_count_for_signature"],
        "repair_scope": run_payload["repair_scope"],
        "repair_recommendation": run_payload["repair_recommendation"],
        "promotion_decision": run_payload["promotion_decision"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
