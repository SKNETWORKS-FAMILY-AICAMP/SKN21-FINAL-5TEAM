from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .job_scheduler import StalledRecoveryDecision, decide_stalled_recovery
from .redis_store import RedisRunJobStore
from .worker_runtime import WorkerRuntime


def reap_stalled_jobs(
    *,
    store: RedisRunJobStore,
    run_id: str,
    redis_client: Any,
    clock: Callable[[], float] | None = None,
) -> list[StalledRecoveryDecision]:
    runtime = WorkerRuntime(store=store, redis_client=redis_client, clock=clock)
    decisions: list[StalledRecoveryDecision] = []

    for job_id in sorted(store.get_run_job_ids(run_id)):
        if not runtime.is_job_stalled(job_id):
            continue

        job_hash = store.get_job(job_id)
        payload = store.get_job_payload(job_id)
        retry_count = int(job_hash.get("retry_count") or 0)
        retry_budget = int(job_hash.get("retry_budget") or payload.get("retry_budget") or 0)
        retryable = _as_bool(job_hash.get("retryable"), default=bool(payload.get("retryable")))
        failure_signature = str(
            job_hash.get("failure_signature")
            or payload.get("failure_signature")
            or "stalled_lease"
        )
        decision = decide_stalled_recovery(
            job_id=job_id,
            retry_count=retry_count,
            retry_budget=retry_budget,
            retryable=retryable,
            failure_signature=failure_signature,
        )
        decisions.append(decision)

        if decision.action == "requeue":
            store.update_job(
                job_id,
                {
                    "status": "queued",
                    "retry_count": str(decision.retry_count),
                    "failure_signature": failure_signature,
                    "failure_reason": "stalled lease recovered",
                },
            )
            store.enqueue_ready_job(job_id)
            continue

        store.update_job(
            job_id,
            {
                "status": "failed",
                "terminal_state": "human_review_required",
                "failure_signature": failure_signature,
                "failure_reason": "stalled lease requires manual review",
            },
        )

    return decisions


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}
