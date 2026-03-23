from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import ArtifactRef


RepairRewindTarget = Literal["validation", "compile", "planning", "analysis"]


class FailureBundle(BaseModel):
    failed_stage: str
    failure_signature: str
    failure_summary: str
    trigger_event_id: str
    related_artifacts: list[ArtifactRef] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    related_file_samples: list[dict[str, str]] = Field(default_factory=list)
    input_artifact_versions: dict[str, int] = Field(default_factory=dict)
    attempt_number: int = 1
    repeat_count: int = 1

    model_config = ConfigDict(extra="forbid")


class RepairDecision(BaseModel):
    failure_signature: str
    diagnosis: str
    rewind_to: RepairRewindTarget
    preserve_artifacts: list[str] = Field(default_factory=list)
    required_rechecks: list[str] = Field(default_factory=list)
    additional_discovery: list[dict[str, str]] = Field(default_factory=list)
    artifact_overrides: dict[str, Any] = Field(default_factory=dict)
    stop: bool = False
    stop_reason: str | None = None

    model_config = ConfigDict(extra="forbid")
