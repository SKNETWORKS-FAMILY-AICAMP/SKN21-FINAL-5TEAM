from __future__ import annotations

from typing import Any


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._expiry: dict[str, int] = {}

    def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs: Any) -> None:
        if mapping is None:
            mapping = {}
        self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key) or {})

    def sadd(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._expiry[key] = ttl_seconds

    def ttl(self, key: str) -> int | None:
        return self._expiry.get(key)


def test_lease_job_records_owner_and_lease_timestamps() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.worker_runtime import WorkerRuntime

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(JobRecord(job_id="planner-001", run_id="run-001", payload={"role": "Planner"}))
    runtime = WorkerRuntime(store, redis_client=fake, clock=lambda: 1000.0)

    runtime.lease_job(job_id="planner-001", worker_id="worker-a", lease_ttl_seconds=30)

    job_hash = fake.hgetall("onboarding:job:planner-001")
    assert job_hash["status"] == "leased"
    assert job_hash["lease_owner"] == "worker-a"
    assert job_hash["leased_at"] == "1000"
    assert job_hash["lease_expires_at"] == "1030"


def test_heartbeat_updates_job_hash_and_ttl_key() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.worker_runtime import WorkerRuntime

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(JobRecord(job_id="planner-001", run_id="run-001", payload={"role": "Planner"}))
    runtime = WorkerRuntime(store, redis_client=fake, clock=lambda: 1050.0)

    runtime.heartbeat_job(job_id="planner-001", worker_id="worker-a", lease_ttl_seconds=15)

    job_hash = fake.hgetall("onboarding:job:planner-001")
    assert job_hash["status"] == "running"
    assert job_hash["heartbeat_at"] == "1050"
    assert job_hash["lease_expires_at"] == "1065"
    assert fake.ttl("onboarding:heartbeat:planner-001") == 15


def test_stalled_job_is_detected_when_lease_has_expired() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.worker_runtime import WorkerRuntime

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(JobRecord(job_id="planner-001", run_id="run-001", payload={"role": "Planner"}))
    fake.hset(
        "onboarding:job:planner-001",
        mapping={
            "status": "running",
            "lease_owner": "worker-a",
            "lease_expires_at": "1049",
        },
    )
    runtime = WorkerRuntime(store, redis_client=fake, clock=lambda: 1050.0)

    stalled = runtime.is_job_stalled("planner-001")

    assert stalled is True
