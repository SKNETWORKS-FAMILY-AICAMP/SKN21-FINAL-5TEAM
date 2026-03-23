from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .redis_store import RedisRunJobStore


class WorkerRuntime:
    def __init__(
        self,
        store: RedisRunJobStore,
        redis_client: Any,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._redis = redis_client
        self._clock = clock or __import__("time").time

    def lease_job(self, job_id: str, worker_id: str, lease_ttl_seconds: int) -> None:
        leased_at = self._now()
        self._store.update_job(
            job_id,
            {
                "status": "leased",
                "lease_owner": worker_id,
                "leased_at": str(leased_at),
                "lease_expires_at": str(leased_at + lease_ttl_seconds),
            },
        )

    def heartbeat_job(self, job_id: str, worker_id: str, lease_ttl_seconds: int) -> None:
        heartbeat_at = self._now()
        self._store.update_job(
            job_id,
            {
                "status": "running",
                "lease_owner": worker_id,
                "heartbeat_at": str(heartbeat_at),
                "lease_expires_at": str(heartbeat_at + lease_ttl_seconds),
            },
        )
        self._redis.expire(self._store.heartbeat_key(job_id), lease_ttl_seconds)

    def complete_job(self, job_id: str) -> None:
        self._store.update_job(job_id, {"status": "completed", "completed_at": str(self._now())})

    def complete_job_with_result(self, job_id: str, result: dict[str, Any]) -> None:
        self._store.update_job(
            job_id,
            {
                "status": "completed",
                "completed_at": str(self._now()),
                "result": json.dumps(result, ensure_ascii=False),
            },
        )

    def fail_job(self, job_id: str, failure_reason: str) -> None:
        self._store.update_job(
            job_id,
            {
                "status": "failed",
                "failed_at": str(self._now()),
                "failure_reason": failure_reason,
            },
        )

    def is_job_stalled(self, job_id: str) -> bool:
        job_hash = self._store.get_job(job_id)
        lease_expires_at = job_hash.get("lease_expires_at")
        if not lease_expires_at:
            return False
        return int(lease_expires_at) < self._now()

    def _now(self) -> int:
        return int(self._clock())
