from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BackendWiringPlan(BaseModel):
    strategy: str
    route_target: str
    import_target: str
    auth_handler_source: str
    generated_handler_path: str | None = None
    chat_auth_contract_path: str = "/api/chat/auth-token"

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "strategy",
        "route_target",
        "import_target",
        "auth_handler_source",
        "generated_handler_path",
        "chat_auth_contract_path",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class FrontendIntegrationPlan(BaseModel):
    mount_strategy: str
    mount_target: str
    router_boundary: str | None = None
    api_strategy: str
    api_client_target: str
    auth_bootstrap_path: str = "/api/chat/auth-token"

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "mount_strategy",
        "mount_target",
        "router_boundary",
        "api_strategy",
        "api_client_target",
        "auth_bootstrap_path",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class DomainAdaptersPlan(BaseModel):
    product_adapter_target: str | None = None
    order_adapter_target: str | None = None
    tool_registry_target: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "product_adapter_target",
        "order_adapter_target",
        "tool_registry_target",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class SupportingArtifactSpec(BaseModel):
    path: str
    kind: str
    reason: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("path", "kind", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()


class PlanningNotes(BaseModel):
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    llm_rationale: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class IntegrationPlan(BaseModel):
    backend_wiring: BackendWiringPlan
    frontend_integration: FrontendIntegrationPlan
    domain_adapters: DomainAdaptersPlan = Field(default_factory=DomainAdaptersPlan)
    supporting_artifacts: list[SupportingArtifactSpec] = Field(default_factory=list)
    planning_notes: PlanningNotes = Field(default_factory=PlanningNotes)

    model_config = ConfigDict(extra="forbid")
