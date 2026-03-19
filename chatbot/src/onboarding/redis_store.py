from __future__ import annotations

import json
from typing import Any

from .redis_models import JobRecord, RunEventRecord, RunRecord


class RedisRunJobStore:
    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    @property
    def redis_client(self) -> Any:
        return self._redis

    def create_run(self, run: RunRecord) -> None:
        self._redis.hset(self._run_key(run.run_id), mapping=run.to_hash())

    def create_job(self, job: JobRecord) -> None:
        self._redis.hset(self._job_key(job.job_id), mapping=job.to_hash())
        self._redis.sadd(self._run_jobs_key(job.run_id), job.job_id)

    def update_job(self, job_id: str, fields: dict[str, str]) -> None:
        self._redis.hset(self._job_key(job_id), mapping=fields)

    def get_job(self, job_id: str) -> dict[str, str]:
        return dict(self._redis.hgetall(self._job_key(job_id)))

    def get_run_job_ids(self, run_id: str) -> set[str]:
        return set(self._redis.smembers(self._run_jobs_key(run_id)))

    def get_job_payload(self, job_id: str) -> dict[str, Any]:
        job_hash = self.get_job(job_id)
        payload = job_hash.get("payload")
        if not payload:
            return {}
        return json.loads(payload)

    def append_event(self, event: RunEventRecord) -> None:
        self._redis.rpush(self._event_key(event.run_id), event.to_payload())

    def enqueue_ready_job(self, job_id: str) -> None:
        self._redis.rpush(self.ready_queue_key(), job_id)

    def pop_ready_job(self) -> str | None:
        return self._redis.lpop(self.ready_queue_key())

    @staticmethod
    def heartbeat_key(job_id: str) -> str:
        return f"onboarding:heartbeat:{job_id}"

    @staticmethod
    def ready_queue_key() -> str:
        return "onboarding:queue:ready"

    @staticmethod
    def _run_key(run_id: str) -> str:
        return f"onboarding:run:{run_id}"

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"onboarding:job:{job_id}"

    @staticmethod
    def _run_jobs_key(run_id: str) -> str:
        return f"onboarding:run:{run_id}:jobs"

    @staticmethod
    def _event_key(run_id: str) -> str:
        return f"onboarding:events:{run_id}"
