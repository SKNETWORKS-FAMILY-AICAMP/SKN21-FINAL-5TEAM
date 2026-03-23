from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.job_scheduler import (
    FailurePolicy,
    JobDescriptor,
    JobEvent,
    RecoveryJob,
    apply_event,
    build_initial_state,
)


def test_no_dependencies_are_runnable_immediately() -> None:
    descriptors = [
        JobDescriptor(job_id="analyzer", depends_on=set()),
        JobDescriptor(job_id="planner", depends_on={"analyzer"}),
    ]

    state = build_initial_state(descriptors)

    assert state.runnable == {"analyzer"}
    assert "planner" not in state.runnable


def test_dependent_job_unblocks_when_upstream_succeeds() -> None:
    descriptors = [
        JobDescriptor(job_id="analyzer", depends_on=set()),
        JobDescriptor(job_id="planner", depends_on={"analyzer"}),
    ]
    state = build_initial_state(descriptors)

    apply_event(state, JobEvent(job_id="analyzer", event_type="job.completed"))

    assert "planner" in state.runnable
    assert "analyzer" in state.completed


def test_failed_job_proposes_diagnostician_workflow() -> None:
    descriptors = [JobDescriptor(job_id="planner", depends_on=set())]
    state = build_initial_state(descriptors)
    policy = FailurePolicy(retryable=True, failure_signature="planner:1")

    apply_event(
        state,
        JobEvent(job_id="planner", event_type="job.failed", failure_policy=policy),
    )
    assert state.recovery_jobs
    job = state.recovery_jobs[-1]
    assert isinstance(job, RecoveryJob)
    assert job.job_id == "planner"
    assert job.retryable is True
    assert job.recovery_type == "retry"
    assert job.failure_signature == "planner:1"
    assert job.role == "Diagnostician"


def test_failed_job_is_removed_from_runnable() -> None:
    descriptors = [JobDescriptor(job_id="planner", depends_on=set())]
    state = build_initial_state(descriptors)
    policy = FailurePolicy(retryable=True, failure_signature="planner:1")

    apply_event(
        state,
        JobEvent(job_id="planner", event_type="job.failed", failure_policy=policy),
    )
    assert "planner" not in state.runnable


def test_structural_failure_routes_to_diagnostician_only() -> None:
    descriptors = [JobDescriptor(job_id="planner", depends_on=set())]
    state = build_initial_state(descriptors)
    policy = FailurePolicy(retryable=False, failure_signature="planner:127")

    apply_event(
        state,
        JobEvent(job_id="planner", event_type="job.failed", failure_policy=policy),
    )
    assert state.recovery_jobs
    job = state.recovery_jobs[-1]
    assert isinstance(job, RecoveryJob)
    assert job.job_id == "planner"
    assert job.retryable is False
    assert job.recovery_type == "diagnose"
    assert job.failure_signature == "planner:127"
    assert job.role == "Diagnostician"
