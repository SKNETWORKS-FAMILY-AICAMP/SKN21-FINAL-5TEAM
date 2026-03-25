from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import PathCandidate


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


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
        return _normalize_text(value)


class WorkspaceProfile(BaseModel):
    root: str
    backend_root: str | None = None
    frontend_root: str | None = None
    manifest_path: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("root", "backend_root", "frontend_root", "manifest_path", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class FrameworkProfile(BaseModel):
    backend_framework: str
    frontend_framework: str
    auth_style: str
    orm_family: str = "unknown"
    confidence_notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "backend_framework",
        "frontend_framework",
        "auth_style",
        "orm_family",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class SearchIntent(BaseModel):
    label: str
    query: str
    rationale: str
    owner: str = "deterministic"

    model_config = ConfigDict(extra="forbid")

    @field_validator("label", "query", "rationale", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class RetrievalPlan(BaseModel):
    search_intents: list[SearchIntent] = Field(default_factory=list)
    read_targets: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CandidateSet(BaseModel):
    route_definitions: list[PathCandidate] = Field(default_factory=list)
    auth_components: list[PathCandidate] = Field(default_factory=list)
    models: list[PathCandidate] = Field(default_factory=list)
    migrations: list[PathCandidate] = Field(default_factory=list)
    api_clients: list[PathCandidate] = Field(default_factory=list)
    app_shells: list[PathCandidate] = Field(default_factory=list)
    router_boundaries: list[PathCandidate] = Field(default_factory=list)
    widget_mounts: list[PathCandidate] = Field(default_factory=list)
    order_targets: list[PathCandidate] = Field(default_factory=list)
    serializers: list[PathCandidate] = Field(default_factory=list)
    schemas: list[PathCandidate] = Field(default_factory=list)
    services: list[PathCandidate] = Field(default_factory=list)
    repositories: list[PathCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReadTarget(BaseModel):
    path: str
    kind: str
    rationale: str
    owner: str = "llm"
    priority: int = 1
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("path", "kind", "rationale", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class EvidencePacket(BaseModel):
    packet_id: str
    kind: str
    path: str
    summary: str
    owner: str = "deterministic"
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("packet_id", "kind", "path", "summary", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class ContractRecord(BaseModel):
    identifier: str
    kind: str
    location: str
    owner: str = "deterministic"
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("identifier", "kind", "location", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class VerifiedContracts(BaseModel):
    database_entities: list[ContractRecord] = Field(default_factory=list)
    api_endpoints: list[ContractRecord] = Field(default_factory=list)
    auth_components: list[ContractRecord] = Field(default_factory=list)
    tool_targets: list[ContractRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AnalysisGraphNode(BaseModel):
    node_id: str
    kind: str
    label: str
    path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("node_id", "kind", "label", "path", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class AnalysisGraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("source", "target", "relation", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class AnalysisGraph(BaseModel):
    nodes: list[AnalysisGraphNode] = Field(default_factory=list)
    edges: list[AnalysisGraphEdge] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RejectedClaim(BaseModel):
    identifier: str
    kind: str
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("identifier", "kind", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


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


class AnalysisBundle(BaseModel):
    workspace_profile: WorkspaceProfile
    framework_profile: FrameworkProfile
    retrieval_plan: RetrievalPlan = Field(default_factory=RetrievalPlan)
    candidate_set: CandidateSet = Field(default_factory=CandidateSet)
    read_queue: list[ReadTarget] = Field(default_factory=list)
    evidence_packets: list[EvidencePacket] = Field(default_factory=list)
    verified_contracts: VerifiedContracts = Field(default_factory=VerifiedContracts)
    rejected_claims: list[RejectedClaim] = Field(default_factory=list)
    analysis_graph: AnalysisGraph = Field(default_factory=AnalysisGraph)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    snapshot: AnalysisSnapshot

    model_config = ConfigDict(extra="forbid")
