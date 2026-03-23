from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ApprovalStore:
    def __init__(self, *, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_request(
        self,
        *,
        run_id: str,
        approval_type: str,
        blocked_job_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._read(run_id, approval_type)
        if current is not None:
            return current

        payload = {
            "request_id": f"{run_id}:{approval_type}",
            "run_id": run_id,
            "approval_type": approval_type,
            "status": "pending",
            "decision": None,
            "actor": None,
            "requested_at": _utc_now(),
            "decided_at": None,
            "consumed_at": None,
            "blocked_job_id": blocked_job_id,
        }
        self._write(run_id, approval_type, payload)
        return payload

    def record_decision(
        self,
        *,
        run_id: str,
        approval_type: str,
        decision: str,
        actor: str,
    ) -> dict[str, Any]:
        payload = self._read(run_id, approval_type)
        if payload is None:
            payload = self.create_request(run_id=run_id, approval_type=approval_type)

        if payload["approval_type"] != approval_type:
            raise ValueError(f"Mismatched approval type for {run_id}: {approval_type}")
        if payload["status"] != "pending":
            return payload

        payload["status"] = "approved" if decision == "approve" else "rejected"
        payload["decision"] = decision
        payload["actor"] = actor
        payload["decided_at"] = _utc_now()
        self._write(run_id, approval_type, payload)
        return payload

    def get_decision(self, *, run_id: str, approval_type: str) -> dict[str, Any] | None:
        payload = self._read(run_id, approval_type)
        if payload is None or payload["approval_type"] != approval_type:
            return None
        return payload

    def consume_decision(self, *, run_id: str, approval_type: str) -> dict[str, Any] | None:
        payload = self.get_decision(run_id=run_id, approval_type=approval_type)
        if payload is None:
            return None
        if payload["status"] == "pending":
            return None
        if payload["status"] == "consumed":
            return payload

        payload["status"] = "consumed"
        payload["consumed_at"] = _utc_now()
        self._write(run_id, approval_type, payload)
        return payload

    def _path(self, run_id: str, approval_type: str) -> Path:
        return self.root / f"{run_id}__{approval_type}.json"

    def _read(self, run_id: str, approval_type: str) -> dict[str, Any] | None:
        path = self._path(run_id, approval_type)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, run_id: str, approval_type: str, payload: dict[str, Any]) -> None:
        self._path(run_id, approval_type).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
