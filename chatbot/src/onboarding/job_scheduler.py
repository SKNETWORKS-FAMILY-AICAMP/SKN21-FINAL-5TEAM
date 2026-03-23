from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(frozen=True)
class JobDescriptor:
    job_id: str
    depends_on: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", frozenset(self.depends_on))


@dataclass(frozen=True)
class FailurePolicy:
    retryable: bool
    failure_signature: str


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    event_type: str
    failure_policy: FailurePolicy | None = None


@dataclass
class RecoveryJob:
    job_id: str
    role: str
    retryable: bool
    failure_signature: str
    recovery_type: str


@dataclass(frozen=True)
class StalledRecoveryDecision:
    job_id: str
    action: str
    retry_count: int
    retry_budget: int
    failure_signature: str


@dataclass
class SchedulerState:
    runnable: set[str]
    blocked: dict[str, JobDescriptor]
    completed: set[str]
    recovery_jobs: list[RecoveryJob]


def build_initial_state(descriptors: Iterable[JobDescriptor]) -> SchedulerState:
    runnable: set[str] = set()
    blocked: dict[str, JobDescriptor] = {}
    for descriptor in descriptors:
        if not descriptor.depends_on:
            runnable.add(descriptor.job_id)
        else:
            blocked[descriptor.job_id] = descriptor
    return SchedulerState(
        runnable=runnable,
        blocked=blocked,
        completed=set(),
        recovery_jobs=[],
    )


def apply_event(state: SchedulerState, event: JobEvent) -> SchedulerState:
    if event.event_type == "job.completed":
        state.completed.add(event.job_id)
        state.runnable.discard(event.job_id)
        newly_runnable = []
        for job_id, descriptor in list(state.blocked.items()):
            if descriptor.depends_on <= state.completed:
                newly_runnable.append(job_id)
        for job_id in newly_runnable:
            state.runnable.add(job_id)
            state.blocked.pop(job_id, None)
        return state

    if event.event_type == "job.failed":
        policy = event.failure_policy or FailurePolicy(retryable=False, failure_signature="unknown")
        recovery_type = "retry" if policy.retryable else "diagnose"
        state.runnable.discard(event.job_id)
        state.recovery_jobs.append(
            RecoveryJob(
                job_id=event.job_id,
                role="Diagnostician",
                retryable=policy.retryable,
                failure_signature=policy.failure_signature,
                recovery_type=recovery_type,
            )
        )
        return state

    raise ValueError(f"Unknown event type: {event.event_type}")


def decide_stalled_recovery(
    *,
    job_id: str,
    retry_count: int,
    retry_budget: int,
    retryable: bool,
    failure_signature: str,
) -> StalledRecoveryDecision:
    if retryable and retry_count < retry_budget:
        return StalledRecoveryDecision(
            job_id=job_id,
            action="requeue",
            retry_count=retry_count + 1,
            retry_budget=retry_budget,
            failure_signature=failure_signature,
        )
    return StalledRecoveryDecision(
        job_id=job_id,
        action="human_review",
        retry_count=retry_count,
        retry_budget=retry_budget,
        failure_signature=failure_signature,
    )
