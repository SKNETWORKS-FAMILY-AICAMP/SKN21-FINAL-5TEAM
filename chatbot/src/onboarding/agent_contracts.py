from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .integration_contracts import (
    BackendContract,
    ChatAuthContract,
    FrontendContract,
    OrderAdapterContract,
    ProductAdapterContract,
    SiteIntegrationContract,
)


class RunState(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    AWAITING_ANALYSIS_APPROVAL = "awaiting_analysis_approval"
    PLANNING = "planning"
    GENERATING = "generating"
    AWAITING_APPLY_APPROVAL = "awaiting_apply_approval"
    APPLYING = "applying"
    VALIDATING = "validating"
    DIAGNOSING = "diagnosing"
    AWAITING_EXPORT_APPROVAL = "awaiting_export_approval"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAILED = "failed"
    REJECTED = "rejected"


class ApprovalType(str, Enum):
    ANALYSIS = "analysis"
    APPLY = "apply"
    EXPORT = "export"


class AgentMessage(BaseModel):
    role: str
    claim: str
    evidence: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    risk: str
    next_action: str
    blocking_issue: str | None = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RunEvent(BaseModel):
    event_type: str
    run_id: str
    state: RunState
    payload: dict[str, Any]
    created_at: str

    model_config = ConfigDict(extra="forbid")


class RecoveryAttempt(BaseModel):
    retry_count: int
    failure_signature: str
    classification: str | None = None
    should_retry: bool
    stop_reason: str | None = None
    recovery_artifact_path: str | None = None

    model_config = ConfigDict(extra="forbid")
