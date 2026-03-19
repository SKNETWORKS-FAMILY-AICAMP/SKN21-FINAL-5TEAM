from __future__ import annotations

from collections.abc import Callable
from typing import cast
from typing import Any

from .redis_models import RunEventRecord
from .redis_store import RedisRunJobStore
from .role_runner import RoleRunner
from .worker_runtime import WorkerRuntime


class WorkerProcess:
    def __init__(
        self,
        *,
        worker_id: str,
        store: RedisRunJobStore,
        redis_client: Any,
        role_runner: RoleRunner | None,
        job_executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.store = store
        self.role_runner = role_runner
        self.job_executors = job_executors or {}
        self.runtime = WorkerRuntime(store=store, redis_client=redis_client, clock=clock)

    def consume_once(self, lease_ttl_seconds: int = 30) -> str | None:
        job_id = self.store.pop_ready_job()
        if job_id is None:
            return None

        job_hash = self.store.get_job(job_id)
        job_payload = self.store.get_job_payload(job_id)
        run_id = job_hash["run_id"]
        role = str(job_payload.get("role") or job_payload.get("job_type") or "unknown")
        job_type = str(job_payload.get("job_type") or "")
        context = dict(job_payload.get("context") or {})

        self.runtime.lease_job(job_id=job_id, worker_id=self.worker_id, lease_ttl_seconds=lease_ttl_seconds)
        self.store.append_event(
            RunEventRecord(
                run_id=run_id,
                event="job.started",
                payload={"job_id": job_id, "role": role, "worker_id": self.worker_id},
            )
        )
        self.runtime.heartbeat_job(job_id=job_id, worker_id=self.worker_id, lease_ttl_seconds=lease_ttl_seconds)

        try:
            result = self._execute_job(role=role, job_type=job_type, context=context)
        except Exception as exc:
            self.runtime.fail_job(job_id, str(exc))
            self.store.append_event(
                RunEventRecord(
                    run_id=run_id,
                    event="job.failed",
                    payload={
                        "job_id": job_id,
                        "role": role,
                        "worker_id": self.worker_id,
                        "error": str(exc),
                    },
                )
            )
            raise

        self.runtime.complete_job_with_result(job_id, result)
        self.store.append_event(
            RunEventRecord(
                run_id=run_id,
                event="job.completed",
                payload={
                    "job_id": job_id,
                    "role": role,
                    "worker_id": self.worker_id,
                    "result": result,
                },
            )
        )
        return job_id

    def _execute_job(self, *, role: str, job_type: str, context: dict[str, Any]) -> dict[str, Any]:
        if job_type:
            executor = self.job_executors.get(job_type)
            if executor is None:
                raise ValueError(f"Unsupported job type: {job_type}")
            return dict(executor(context))

        if self.role_runner is None:
            raise ValueError(f"Missing role runner for role job: {role}")
        message = cast(RoleRunner, self.role_runner).run_role(role, context)
        return message.model_dump()
