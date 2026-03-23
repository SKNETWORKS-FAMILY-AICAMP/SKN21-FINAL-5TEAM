from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import ArtifactRef


class ApplyBundleResult(BaseModel):
    bundle_id: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ApplyResult(BaseModel):
    workspace_path: str
    host_workspace_path: str
    chatbot_workspace_path: str
    passed: bool
    applied_files: list[str] = Field(default_factory=list)
    host_applied_files: list[str] = Field(default_factory=list)
    chatbot_applied_files: list[str] = Field(default_factory=list)
    applied_bundles: list[ApplyBundleResult] = Field(default_factory=list)
    failed_bundles: list[ApplyBundleResult] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReplayResult(BaseModel):
    replay_workspace_path: str
    host_replay_workspace_path: str
    chatbot_replay_workspace_path: str
    host_patch_path: str
    chatbot_patch_path: str
    passed: bool
    applied_patch_artifacts: list[str] = Field(default_factory=list)
    failed_patch_artifacts: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class BackendRuntimeCommandResult(BaseModel):
    name: str
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    passed: bool
    skipped: bool = False

    model_config = ConfigDict(extra="forbid")


class BackendRuntimePrepResult(BaseModel):
    framework: str
    passed: bool
    failure_summary: str | None = None
    backend_root: str | None = None
    venv_path: str | None = None
    python_executable: str | None = None
    create_venv: BackendRuntimeCommandResult | None = None
    install: BackendRuntimeCommandResult | None = None
    migrate: BackendRuntimeCommandResult | None = None
    seed: BackendRuntimeCommandResult | None = None
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class BackendRuntimePlan(BaseModel):
    framework: str
    backend_root: str
    command: list[str]
    readiness_url: str
    environment: dict[str, str] = Field(default_factory=dict)
    python_executable: str | None = None

    model_config = ConfigDict(extra="forbid")


class BackendRuntimeState(BaseModel):
    framework: str
    passed: bool
    pid: int | None = None
    command: list[str] = Field(default_factory=list)
    readiness_url: str | None = None
    readiness: dict[str, Any] = Field(default_factory=dict)
    failure_summary: str | None = None
    stdout: str = ""
    stderr: str = ""
    related_files: list[str] = Field(default_factory=list)
    process_handle: Any | None = Field(default=None, exclude=True, repr=False)

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class SmokeRunResult(BaseModel):
    passed: bool
    results: list[dict[str, Any]] = Field(default_factory=list)
    failure_summary: str | None = None
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WidgetOrderE2EResult(BaseModel):
    passed: bool
    failure_summary: str
    covered_flows: list[str] = Field(default_factory=list)
    flow_reports: dict[str, Any] = Field(default_factory=dict)
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ValidationBundle(BaseModel):
    stage: str = "validation"
    passed: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    failure_signature: str | None = None
    failure_summary: str | None = None
    related_files: list[str] = Field(default_factory=list)
    related_artifacts: list[ArtifactRef] = Field(default_factory=list)
    input_artifact_versions: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
