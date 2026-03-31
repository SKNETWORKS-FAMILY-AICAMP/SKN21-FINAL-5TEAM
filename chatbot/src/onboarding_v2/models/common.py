from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactRef(BaseModel):
    stage: str
    artifact_type: str
    version: int
    path: str
    content_hash: str

    model_config = ConfigDict(extra="forbid")


class ArtifactEnvelope(BaseModel):
    artifact_id: str
    artifact_type: str
    stage: str
    version: int
    schema_version: str = "1.0"
    created_at: str
    producer: str
    attempt: int = 1
    input_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    event_ref: str | None = None
    status: str = "completed"
    provenance: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class EventRecord(BaseModel):
    event_id: str
    run_id: str
    timestamp: str
    stage: str
    phase: str
    event_type: str
    severity: str = "info"
    actor: str = "system"
    attempt: int = 1
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    failure_signature: str | None = None
    rewind_to: str | None = None
    requested_rewind_to: str | None = None
    effective_rewind_to: str | None = None
    source: str = "deterministic"

    model_config = ConfigDict(extra="forbid")


class StageLatestView(BaseModel):
    stage: str
    latest_artifact: ArtifactRef | None = None
    artifact_count: int = 0

    model_config = ConfigDict(extra="forbid")


class RunSummaryView(BaseModel):
    run_id: str
    site: str
    status: str
    latest_failure_signature: str | None = None
    latest_rewind_to: str | None = None
    repair_attempt_count: int = 0
    stopped_for_review: bool = False
    latest_event_id: str | None = None
    retrieval_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    final_capability_profile: str | None = None
    enabled_retrieval_corpora: list[str] = Field(default_factory=list)
    stages: list[StageLatestView] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class DebugRecord(BaseModel):
    stage: str
    attempt: int = 1
    prompt: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    normalized_response: dict[str, Any] = Field(default_factory=dict)
    parse_result: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    event_ref: str | None = None
    requested_rewind_to: str | None = None
    effective_rewind_to: str | None = None

    model_config = ConfigDict(extra="forbid")


class PathCandidate(BaseModel):
    path: str
    reason: str
    source: str = "heuristic"
    confidence: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("path", "reason", "source", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()
