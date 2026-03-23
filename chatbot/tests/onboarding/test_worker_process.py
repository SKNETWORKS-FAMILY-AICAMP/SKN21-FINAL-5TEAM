from __future__ import annotations

import json
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

    def rpush(self, key: str, value: str) -> None:
        self._lists.setdefault(key, []).append(value)

    def lpop(self, key: str) -> str | None:
        values = self._lists.get(key, [])
        if not values:
            return None
        return values.pop(0)

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


def test_worker_process_executes_ready_job_and_persists_result() -> None:
    from chatbot.src.onboarding.redis_models import JobRecord
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.role_runner import RoleRunner
    from chatbot.src.onboarding.worker_process import WorkerProcess

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    store.create_job(
        JobRecord(
            job_id="run-001:Analyzer:1",
            run_id="run-001",
            payload={"role": "Analyzer", "context": {"site": "food", "evidence": ["users/views.py"]}},
        )
    )
    store.enqueue_ready_job("run-001:Analyzer:1")
    runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": f"{context['site']} 분석 완료",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low",
                "next_action": "Planner로 전달",
                "blocking_issue": None,
            }
        }
    )

    process = WorkerProcess(
        worker_id="worker-a",
        store=store,
        redis_client=fake,
        role_runner=runner,
        clock=lambda: 1000.0,
    )

    processed_job_id = process.consume_once(lease_ttl_seconds=30)

    assert processed_job_id == "run-001:Analyzer:1"
    job_hash = fake.hgetall("onboarding:job:run-001:Analyzer:1")
    assert job_hash["status"] == "completed"
    result = json.loads(job_hash["result"])
    assert result["role"] == "Analyzer"
    assert result["claim"] == "food 분석 완료"

    entries = [
        json.loads(entry)
        for entry in fake.lrange("onboarding:events:run-001", 0, -1)
    ]
    assert [entry["event"] for entry in entries] == ["job.started", "job.completed"]
    assert entries[-1]["payload"]["role"] == "Analyzer"
    assert entries[-1]["payload"]["job_id"] == "run-001:Analyzer:1"


def test_worker_process_returns_none_when_ready_queue_is_empty() -> None:
    from chatbot.src.onboarding.redis_store import RedisRunJobStore
    from chatbot.src.onboarding.role_runner import RoleRunner
    from chatbot.src.onboarding.worker_process import WorkerProcess

    fake = _FakeRedis()
    store = RedisRunJobStore(fake)
    runner = RoleRunner(responders={})
    process = WorkerProcess(
        worker_id="worker-a",
        store=store,
        redis_client=fake,
        role_runner=runner,
        clock=lambda: 1000.0,
    )

    processed_job_id = process.consume_once(lease_ttl_seconds=30)

    assert processed_job_id is None
