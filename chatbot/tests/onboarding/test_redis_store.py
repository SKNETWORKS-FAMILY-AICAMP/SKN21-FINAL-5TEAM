from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class _FakeRedis:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}

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


@dataclass
class _RunRecord:
    run_id: str
    metadata: dict[str, Any]


@dataclass
class _JobRecord:
    job_id: str
    run_id: str
    payload: dict[str, Any]


@dataclass
class _EventRecord:
    run_id: str
    event: str
    payload: dict[str, Any]


def test_run_creation_writes_run_hash() -> None:
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.redis_models import RunRecord

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    record = RunRecord(run_id="food-run-101", metadata={"site": "food"})

    store.create_run(record)

    stored = fake.hgetall("onboarding:run:food-run-101")
    assert stored == {"run_id": "food-run-101", "metadata": json.dumps({"site": "food"})}


def test_job_creation_writes_job_hash_and_run_set() -> None:
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.redis_models import JobRecord

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    job = JobRecord(job_id="planner-001", run_id="food-run-101", payload={"role": "Planner"})

    store.create_job(job)

    job_hash = fake.hgetall("onboarding:job:planner-001")
    assert job_hash["job_id"] == "planner-001"
    assert job_hash["run_id"] == "food-run-101"
    assert json.loads(job_hash["payload"]) == {"role": "Planner"}

    assert "planner-001" in fake.smembers("onboarding:run:food-run-101:jobs")


def test_event_append_pushes_event_stream() -> None:
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.redis_models import RunEventRecord

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    event = RunEventRecord(run_id="food-run-101", event="job.started", payload={"job": "planner-001"})

    store.append_event(event)

    entries = fake.lrange("onboarding:events:food-run-101", 0, -1)
    assert len(entries) == 1
    parsed = json.loads(entries[0])
    assert parsed["event"] == "job.started"
    assert parsed["payload"]["job"] == "planner-001"
