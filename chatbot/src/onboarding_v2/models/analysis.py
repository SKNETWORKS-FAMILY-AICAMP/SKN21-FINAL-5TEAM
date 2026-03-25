from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import PathCandidate


class RepoProfile(BaseModel):
    site: str
    source_root: str
    backend_framework: str
    frontend_framework: str
    auth_style: str
    backend_entrypoints: list[str] = Field(default_factory=list)
    frontend_entrypoints: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "site",
        "source_root",
        "backend_framework",
        "frontend_framework",
        "auth_style",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()


class BackendSeams(BaseModel):
    auth_source_candidates: list[PathCandidate] = Field(default_factory=list)
    user_resolver_candidates: list[PathCandidate] = Field(default_factory=list)
    route_registration_points: list[PathCandidate] = Field(default_factory=list)
    tool_registry_candidates: list[PathCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FrontendSeams(BaseModel):
    app_shell_candidates: list[PathCandidate] = Field(default_factory=list)
    router_boundary_candidates: list[PathCandidate] = Field(default_factory=list)
    api_client_candidates: list[PathCandidate] = Field(default_factory=list)
    widget_mount_candidates: list[PathCandidate] = Field(default_factory=list)
    auth_store_candidates: list[PathCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class DomainIntegration(BaseModel):
    product_api_base_paths: list[str] = Field(default_factory=list)
    order_api_base_paths: list[str] = Field(default_factory=list)
    order_bridge_targets: list[PathCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AmbiguitySnapshot(BaseModel):
    open_questions: list[str] = Field(default_factory=list)
    competing_candidates: list[PathCandidate] = Field(default_factory=list)
    rejected_candidates: list[PathCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AnalysisProvenance(BaseModel):
    discovered_by: list[str] = Field(default_factory=lambda: ["heuristic"])
    llm_augmented: bool = False
    soft_dropped_candidates: list[PathCandidate] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AnalysisSnapshot(BaseModel):
    repo_profile: RepoProfile
    backend_seams: BackendSeams
    frontend_seams: FrontendSeams
    domain_integration: DomainIntegration
    ambiguity: AmbiguitySnapshot = Field(default_factory=AmbiguitySnapshot)
    provenance: AnalysisProvenance = Field(default_factory=AnalysisProvenance)

    model_config = ConfigDict(extra="forbid")
