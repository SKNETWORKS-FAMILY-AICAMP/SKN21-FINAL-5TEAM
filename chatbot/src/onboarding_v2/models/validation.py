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
    host_source_snapshot_path: str | None = None
    chatbot_source_snapshot_path: str | None = None
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
    host_baseline_root: str | None = None
    chatbot_baseline_root: str | None = None
    passed: bool
    target_match_passed: bool = True
    static_validation_passed: bool = True
    mismatched_targets: list[str] = Field(default_factory=list)
    static_validation_summary: str | None = None
    host_allowed_targets: list[str] = Field(default_factory=list)
    chatbot_allowed_targets: list[str] = Field(default_factory=list)
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
    skipped_reason: str | None = None
    log_path: str | None = None
    duration_ms: int | None = None

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
    reset: BackendRuntimeCommandResult | None = None
    seed: BackendRuntimeCommandResult | None = None
    seed_source_path: str | None = None
    reset_source_path: str | None = None
    fixture_manifest: dict[str, Any] = Field(default_factory=dict)
    env_source: dict[str, Any] = Field(default_factory=dict)
    live_log_paths: dict[str, str] = Field(default_factory=dict)
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class BackendRuntimePlan(BaseModel):
    framework: str
    backend_root: str
    command: list[str]
    readiness_url: str
    listen_port: int | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    python_executable: str | None = None
    launcher_mode: str | None = None
    launcher_metadata_path: str | None = None

    model_config = ConfigDict(extra="forbid")


class BackendRuntimeState(BaseModel):
    framework: str
    passed: bool
    pid: int | None = None
    command: list[str] = Field(default_factory=list)
    readiness_url: str | None = None
    listen_port: int | None = None
    launcher_mode: str | None = None
    startup_hooks_skipped: list[str] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)
    launcher_log_path: str | None = None
    readiness_probe_log_path: str | None = None
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


class OrderActionCapability(BaseModel):
    requires_order_selection: bool = False
    requires_option_selection: bool = False
    allows_direct_execution: bool = True

    model_config = ConfigDict(extra="forbid")


class ValidationCapabilityContract(BaseModel):
    supports_authenticated_chat: bool = True
    supports_widget_order_flow: bool = True
    supports_direct_order_lookup: bool = True
    supports_mutations: bool = True
    supports_retrieval: bool = False
    supports_image_upload: bool = False
    requires_order_selection_for_actions: bool = False
    requires_option_selection_for_exchange: bool = False
    available_actions: list[str] = Field(default_factory=list)
    action_capabilities: dict[str, OrderActionCapability] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ConversationScenarioContract(BaseModel):
    scenario_id: str
    mode: str
    prompt: str
    expected_milestones: list[str] = Field(default_factory=list)
    allowed_paths: list[list[str]] = Field(default_factory=list)
    sampled_order_id: str | None = None
    sampled_option_id: str | None = None
    previous_state_from: str | None = None

    model_config = ConfigDict(extra="forbid")


class WidgetOrderE2EResult(BaseModel):
    passed: bool
    failure_summary: str
    covered_flows: list[str] = Field(default_factory=list)
    flow_reports: dict[str, Any] = Field(default_factory=dict)
    validation_capability_contract: dict[str, Any] = Field(default_factory=dict)
    sampled_order_id: str | None = None
    sampled_option_id: str | None = None
    scenario_mode: str | None = None
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ConversationScenarioResult(BaseModel):
    scenario_id: str
    mode: str
    conversation_id: str
    deterministic_passed: bool
    llm_passed: bool | None = None
    final_verdict: str
    failure_category: str | None = None
    transcript_path: str | None = None
    trace_path: str | None = None
    log_path: str | None = None
    sampled_or_fixture_order_id: str | None = None
    sampled_or_fixture_option_id: str | None = None
    deterministic_failures: list[str] = Field(default_factory=list)
    expected_tool_names: list[str] = Field(default_factory=list)
    observed_tool_names: list[str] = Field(default_factory=list)
    expected_milestones: list[str] = Field(default_factory=list)
    observed_milestones: list[str] = Field(default_factory=list)
    allowed_paths: list[list[str]] = Field(default_factory=list)
    llm_judgement: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ConversationValidationResult(BaseModel):
    passed: bool
    failure_summary: str | None = None
    fixture_manifest: dict[str, Any] = Field(default_factory=dict)
    validation_capability_contract: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[ConversationScenarioResult] = Field(default_factory=list)
    transcript_contents: dict[str, str] = Field(default_factory=dict)
    trace_contents: dict[str, str] = Field(default_factory=dict)
    related_files: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    summary: str
    blocking: bool = True
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ValidationBundle(BaseModel):
    stage: str = "validation"
    passed: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    advisory_failures: list[str] = Field(default_factory=list)
    failure_signature: str | None = None
    failure_summary: str | None = None
    related_files: list[str] = Field(default_factory=list)
    related_artifacts: list[ArtifactRef] = Field(default_factory=list)
    input_artifact_versions: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
