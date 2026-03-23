from __future__ import annotations

from typing import Any


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._expiry: dict[str, int] = {}

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs: Any) -> None:
        if mapping is None:
            mapping = {}
        self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key) or {})

    def sadd(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key) or set())

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self._lists.get(key, [])
        if stop < 0:
            stop = len(values) + stop
        if stop < 0:
            return []
        stop = min(stop, len(values) - 1)
        if start >= len(values):
            return []
        return list(values[start : stop + 1])

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._expiry[key] = ttl_seconds


def test_reaper_requeues_stalled_job_with_remaining_retry_budget() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.reaper import reap_stalled_jobs

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(
        JobRecord(
            job_id="run-001:Analyzer:1",
            run_id="run-001",
            payload={
                "role": "Analyzer",
                "retryable": True,
                "retry_budget": 2,
                "failure_signature": "heartbeat_timeout",
            },
        )
    )
    store.update_job(
        "run-001:Analyzer:1",
        {
            "status": "running",
            "lease_owner": "worker-a",
            "lease_expires_at": "999",
            "retry_count": "0",
        },
    )

    decisions = reap_stalled_jobs(store=store, run_id="run-001", redis_client=fake, clock=lambda: 1000.0)

    job_hash = fake.hgetall("onboarding:job:run-001:Analyzer:1")
    assert decisions[0].action == "requeue"
    assert job_hash["status"] == "queued"
    assert job_hash["retry_count"] == "1"
    assert fake.lrange("onboarding:queue:ready", 0, -1) == ["run-001:Analyzer:1"]


def test_reaper_escalates_stalled_job_when_retry_budget_is_exhausted() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.reaper import reap_stalled_jobs

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(
        JobRecord(
            job_id="run-001:Validator:1",
            run_id="run-001",
            payload={
                "role": "Validator",
                "retryable": True,
                "retry_budget": 1,
                "failure_signature": "heartbeat_timeout",
            },
        )
    )
    store.update_job(
        "run-001:Validator:1",
        {
            "status": "running",
            "lease_owner": "worker-a",
            "lease_expires_at": "999",
            "retry_count": "1",
        },
    )

    decisions = reap_stalled_jobs(store=store, run_id="run-001", redis_client=fake, clock=lambda: 1000.0)

    job_hash = fake.hgetall("onboarding:job:run-001:Validator:1")
    assert decisions[0].action == "human_review"
    assert job_hash["status"] == "failed"
    assert job_hash["terminal_state"] == "human_review_required"
    assert fake.lrange("onboarding:queue:ready", 0, -1) == []
