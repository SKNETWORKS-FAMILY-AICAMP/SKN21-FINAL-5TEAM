from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_ORDER_TOOLS = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]


class HostBackendPlan(BaseModel):
    strategy: str
    route_target: str
    import_target: str
    order_lookup_target: str = "backend/orders/views.py"
    order_action_target: str = "backend/orders/views.py"
    exchange_strategy: str = "augment_existing_order_action_endpoint"
    supported_order_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_ORDER_TOOLS))
    auth_handler_source: str
    generated_handler_path: str | None = None
    chat_auth_contract_path: str = "/api/chat/auth-token"
    site_id: str

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "strategy",
        "route_target",
        "import_target",
        "order_lookup_target",
        "order_action_target",
        "exchange_strategy",
        "auth_handler_source",
        "generated_handler_path",
        "chat_auth_contract_path",
        "site_id",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class HostFrontendPlan(BaseModel):
    mount_strategy: str
    mount_target: str
    router_boundary: str | None = None
    api_strategy: str
    api_client_target: str
    auth_bootstrap_path: str = "/api/chat/auth-token"
    chatbot_server_base_url: str
    chatbot_server_base_url_expression: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "mount_strategy",
        "mount_target",
        "router_boundary",
        "api_strategy",
        "api_client_target",
        "auth_bootstrap_path",
        "chatbot_server_base_url",
        "chatbot_server_base_url_expression",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class ChatbotBridgePlan(BaseModel):
    site_key: str
    adapter_package: str
    setup_target: str
    host_base_url_env_var: str
    supported_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_ORDER_TOOLS))
    runtime_base_url: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "site_key",
        "adapter_package",
        "setup_target",
        "host_base_url_env_var",
        "supported_tools",
        "runtime_base_url",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item).strip() for item in value]
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
    host_backend: HostBackendPlan
    host_frontend: HostFrontendPlan
    chatbot_bridge: ChatbotBridgePlan
    planning_notes: PlanningNotes = Field(default_factory=PlanningNotes)

    model_config = ConfigDict(extra="forbid")

    @property
    def backend_wiring(self) -> HostBackendPlan:
        return self.host_backend

    @property
    def frontend_integration(self) -> HostFrontendPlan:
        return self.host_frontend


# Backward-compatible aliases for transitional code paths.
BackendWiringPlan = HostBackendPlan
FrontendIntegrationPlan = HostFrontendPlan
