from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_ORDER_TOOLS = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]
READ_ONLY_ORDER_TOOLS = [
    "list_orders",
    "get_order_status",
]
DEFAULT_REQUEST_FIELD_MAPPINGS = {
    "action": "action",
    "reason": "reason",
    "new_option_id": "new_option_id",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _normalize_auth_transport(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized == "session_token_cookie":
        return "session_cookie"
    return normalized


class HostBackendPlan(BaseModel):
    strategy: str
    route_target: str
    import_target: str
    login_endpoint: str
    order_lookup_target: str = "backend/orders/views.py"
    order_action_target: str = "backend/orders/views.py"
    exchange_strategy: str = "augment_existing_order_action_endpoint"
    order_action_request_field: str = "action"
    order_action_reason_field: str = "reason"
    order_action_new_option_field: str = "new_option_id"
    order_action_response_serializer: str = "serialize_order"
    exchange_status_transition: str = "EXCHANGE_REQUESTED"
    supported_order_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_ORDER_TOOLS))
    auth_handler_source: str
    generated_handler_path: str | None = None
    chat_auth_contract_path: str = "/api/chat/auth-token"
    site_id: str
    capability_profile: str = "order_cs_only"
    enabled_retrieval_corpora: list[str] = Field(default_factory=list)
    widget_features: dict[str, Any] = Field(default_factory=lambda: {"image_upload": False})

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "strategy",
        "route_target",
        "import_target",
        "login_endpoint",
        "order_lookup_target",
        "order_action_target",
        "exchange_strategy",
        "order_action_request_field",
        "order_action_reason_field",
        "order_action_new_option_field",
        "order_action_response_serializer",
        "exchange_status_transition",
        "auth_handler_source",
        "generated_handler_path",
        "chat_auth_contract_path",
        "site_id",
        "capability_profile",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class HostFrontendPlan(BaseModel):
    mount_strategy: str
    mount_target: str
    router_boundary: str | None = None
    api_strategy: str
    api_client_target: str
    auth_bootstrap_path: str = "/api/chat/auth-token"
    chatbot_server_base_url: str
    chatbot_server_base_url_expression: str = ""
    capability_profile: str = "order_cs_only"
    enabled_retrieval_corpora: list[str] = Field(default_factory=list)
    widget_features: dict[str, Any] = Field(default_factory=lambda: {"image_upload": False})

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
        "capability_profile",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class ResolvedAuthContract(BaseModel):
    transport: str = "session_cookie"
    session_cookie_name: str | None = None
    csrf_cookie_name: str | None = None
    csrf_header_name: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "transport",
        "session_cookie_name",
        "csrf_cookie_name",
        "csrf_header_name",
        mode="before",
    )
    @classmethod
    def _normalize_contract_fields(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = _normalize_optional_text(value)
            if normalized in {"session_token_cookie", "session_cookie"}:
                return "session_cookie"
            return normalized
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _normalize_transport_shape(self) -> "ResolvedAuthContract":
        if self.transport == "bearer_token":
            self.session_cookie_name = None
            self.csrf_cookie_name = None
            self.csrf_header_name = None
        elif self.transport == "session_cookie":
            self.csrf_cookie_name = None
            self.csrf_header_name = None
        return self


class ResolvedRequestFieldContract(BaseModel):
    action: str = "action"
    reason: str = "reason"
    new_option_id: str = "new_option_id"

    model_config = ConfigDict(extra="forbid")

    @field_validator("action", "reason", "new_option_id", mode="before")
    @classmethod
    def _normalize_fields(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class ResolvedResponseContract(BaseModel):
    user_profile: str = "wrapped_user"
    product_profile: str = "list_items_named_price"
    order_profile: str = "rest_detail_wrapped_order"
    delivery_profile: str = "rest_detail_wrapped_order"
    order_status_profile: str = "english_tokens"
    delivery_status_profile: str = "english_tokens"
    order_identifier_mode: str = "direct_order_id"

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "user_profile",
        "product_profile",
        "order_profile",
        "delivery_profile",
        "order_status_profile",
        "delivery_status_profile",
        "order_identifier_mode",
        mode="before",
    )
    @classmethod
    def _normalize_fields(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def _hydrate_profiles(self) -> "ResolvedResponseContract":
        if self.order_profile == "orders_collection_scan":
            self.user_profile = self.user_profile or "orders_collection_user_id"
            self.product_profile = self.product_profile or "products_wrapper_collection"
            self.delivery_profile = self.delivery_profile or "orders_collection_scan"
            self.order_status_profile = self.order_status_profile or "korean_labels"
            self.delivery_status_profile = self.delivery_status_profile or "korean_labels"
            self.order_identifier_mode = self.order_identifier_mode or "direct_order_id"
            return self
        if self.order_profile == "user_scoped_order_service":
            self.user_profile = self.user_profile or "direct_user_session"
            self.product_profile = self.product_profile or "catalog_items_keyword_results"
            self.delivery_profile = self.delivery_profile or "shipping_tracking_record"
            self.order_status_profile = self.order_status_profile or "service_tokens"
            self.delivery_status_profile = self.delivery_status_profile or "service_tokens"
            self.order_identifier_mode = (
                self.order_identifier_mode or "order_number_with_internal_resolution"
            )
            return self
        self.user_profile = self.user_profile or "wrapped_user"
        self.product_profile = self.product_profile or "list_items_named_price"
        self.delivery_profile = self.delivery_profile or "rest_detail_wrapped_order"
        self.order_status_profile = self.order_status_profile or "english_tokens"
        self.delivery_status_profile = self.delivery_status_profile or "english_tokens"
        self.order_identifier_mode = self.order_identifier_mode or "direct_order_id"
        return self


class ResolvedOrderActionContract(BaseModel):
    submission_mode: str = "single_endpoint_json_body"
    supported_actions: list[str] = Field(default_factory=lambda: list(DEFAULT_ORDER_TOOLS))
    request_fields: ResolvedRequestFieldContract = Field(
        default_factory=ResolvedRequestFieldContract
    )
    reason_transport: str | None = None
    new_option_transport: str | None = None
    result_profile: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "submission_mode",
        "reason_transport",
        "new_option_transport",
        "result_profile",
        mode="before",
    )
    @classmethod
    def _normalize_fields(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("supported_actions", mode="before")
    @classmethod
    def _normalize_supported_actions(cls, value: Any) -> list[str]:
        if value is None:
            return list(DEFAULT_ORDER_TOOLS)
        return [str(item).strip() for item in list(value) if str(item).strip()]

    @model_validator(mode="before")
    @classmethod
    def _hydrate_request_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        raw_fields = payload.get("request_fields")
        if raw_fields is None:
            raw_fields = dict(payload.get("request_field_mappings") or {})
        payload["request_fields"] = (
            raw_fields
            if isinstance(raw_fields, ResolvedRequestFieldContract)
            else ResolvedRequestFieldContract.model_validate(raw_fields or {})
        )
        return payload

    @model_validator(mode="after")
    def _hydrate_shape(self) -> "ResolvedOrderActionContract":
        if self.submission_mode == "read_only":
            self.supported_actions = [
                action
                for action in self.supported_actions
                if action in READ_ONLY_ORDER_TOOLS
            ] or list(READ_ONLY_ORDER_TOOLS)
            self.reason_transport = "unsupported"
            self.new_option_transport = "unsupported"
            self.result_profile = self.result_profile or "not_supported"
            return self
        if self.submission_mode == "per_action_query_endpoint":
            self.reason_transport = self.reason_transport or "query_param"
            self.new_option_transport = (
                self.new_option_transport
                or ("query_param" if "exchange" in self.supported_actions else "unsupported")
            )
            self.result_profile = self.result_profile or "requested_message"
            return self
        self.reason_transport = self.reason_transport or "json_body"
        self.new_option_transport = self.new_option_transport or "json_body"
        self.result_profile = self.result_profile or "accepted_message"
        return self


class ChatbotBridgePlan(BaseModel):
    site_key: str
    adapter_package: str
    setup_target: str
    host_base_url_env_var: str
    auth_validation_endpoint: str
    current_user_endpoint: str
    product_search_endpoint: str
    order_list_endpoint: str
    order_detail_endpoint: str
    order_action_endpoint: str
    order_action_endpoints: dict[str, str] = Field(default_factory=dict)
    auth_contract: ResolvedAuthContract = Field(default_factory=ResolvedAuthContract)
    response_contract: ResolvedResponseContract = Field(
        default_factory=ResolvedResponseContract
    )
    order_action_contract: ResolvedOrderActionContract = Field(
        default_factory=ResolvedOrderActionContract
    )
    auth_transport: str = "session_cookie"
    session_cookie_name: str | None = None
    csrf_cookie_name: str | None = None
    csrf_header_name: str | None = None
    response_mapping_profile: str = "rest_detail_wrapped_order"
    request_field_mappings: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_REQUEST_FIELD_MAPPINGS))
    supported_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_ORDER_TOOLS))
    runtime_base_url: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _hydrate_auth_contract(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        raw_contract = payload.get("auth_contract")
        if raw_contract is None:
            raw_contract = {
                key: item
                for key, item in {
                    "transport": payload.get("auth_transport"),
                    "session_cookie_name": payload.get("session_cookie_name"),
                    "csrf_cookie_name": payload.get("csrf_cookie_name"),
                    "csrf_header_name": payload.get("csrf_header_name"),
                }.items()
                if item is not None
            }
        contract = raw_contract if isinstance(raw_contract, ResolvedAuthContract) else ResolvedAuthContract.model_validate(raw_contract)
        payload["auth_contract"] = contract
        payload["auth_transport"] = contract.transport
        payload["session_cookie_name"] = contract.session_cookie_name
        payload["csrf_cookie_name"] = contract.csrf_cookie_name
        payload["csrf_header_name"] = contract.csrf_header_name
        raw_response_contract = payload.get("response_contract")
        if raw_response_contract is None:
            raw_response_contract = {}
            if payload.get("response_mapping_profile") is not None:
                raw_response_contract["order_profile"] = payload.get(
                    "response_mapping_profile"
                )
        response_contract = (
            raw_response_contract
            if isinstance(raw_response_contract, ResolvedResponseContract)
            else ResolvedResponseContract.model_validate(raw_response_contract or {})
        )
        payload["response_contract"] = response_contract
        payload["response_mapping_profile"] = response_contract.order_profile

        raw_order_action_contract = payload.get("order_action_contract")
        if raw_order_action_contract is None:
            raw_order_action_contract = {
                "submission_mode": _derive_legacy_submission_mode(
                    payload.get("supported_tools")
                ),
            }
            if payload.get("supported_tools") is not None:
                raw_order_action_contract["supported_actions"] = payload.get(
                    "supported_tools"
                )
            if payload.get("request_field_mappings") is not None:
                raw_order_action_contract["request_fields"] = payload.get(
                    "request_field_mappings"
                )
        order_action_contract = (
            raw_order_action_contract
            if isinstance(raw_order_action_contract, ResolvedOrderActionContract)
            else ResolvedOrderActionContract.model_validate(raw_order_action_contract or {})
        )
        payload["order_action_contract"] = order_action_contract
        payload["request_field_mappings"] = (
            order_action_contract.request_fields.model_dump(mode="json")
        )
        payload["supported_tools"] = list(order_action_contract.supported_actions)
        return payload

    @field_validator(
        "site_key",
        "adapter_package",
        "setup_target",
        "host_base_url_env_var",
        "auth_validation_endpoint",
        "current_user_endpoint",
        "product_search_endpoint",
        "order_list_endpoint",
        "order_detail_endpoint",
        "order_action_endpoint",
        "supported_tools",
        "response_mapping_profile",
        "runtime_base_url",
        "session_cookie_name",
        "csrf_cookie_name",
        "csrf_header_name",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item).strip() for item in value]
        return _normalize_text(value)

    @field_validator("auth_transport", mode="before")
    @classmethod
    def _normalize_auth_transport(cls, value: Any) -> str | None:
        return _normalize_auth_transport(value)


def _derive_legacy_submission_mode(supported_tools: Any) -> str:
    normalized_tools = [
        str(item).strip() for item in list(supported_tools or []) if str(item).strip()
    ]
    if normalized_tools and not any(
        action in normalized_tools for action in ("cancel", "refund", "exchange")
    ):
        return "read_only"
    return "single_endpoint_json_body"


class IntegrationStrategy(BaseModel):
    backend_strategy: str
    frontend_mount_strategy: str
    frontend_api_strategy: str
    chatbot_bridge_strategy: str = "generated_adapter_package"
    owner: str = "deterministic"

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "backend_strategy",
        "frontend_mount_strategy",
        "frontend_api_strategy",
        "chatbot_bridge_strategy",
        "owner",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class TargetBinding(BaseModel):
    capability: str
    target_path: str
    selection_reason: str
    selection_mode: str = "deterministic"
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("capability", "target_path", "selection_reason", "selection_mode", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class PlannedOperation(BaseModel):
    operation: str
    stage: str
    target_path: str
    strategy: str
    execution_mode: str = "deterministic"
    depends_on: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "operation",
        "stage",
        "target_path",
        "strategy",
        "execution_mode",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class PlannedValidation(BaseModel):
    name: str
    kind: str
    target: str
    success_signal: str
    owner: str = "deterministic"

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "kind", "target", "success_signal", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class PlanningRisk(BaseModel):
    code: str
    summary: str
    severity: str = "medium"
    owner: str = "llm-ready"
    mitigations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", "summary", "severity", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class SupportingArtifactSpec(BaseModel):
    path: str
    kind: str
    reason: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("path", "kind", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class PlanningNotes(BaseModel):
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    llm_rationale: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RagCorpusPlan(BaseModel):
    corpus: str
    enabled: bool = True
    chunking_strategy: str
    collection_alias: str
    build_collection: str
    sources: list[str] = Field(default_factory=list)
    smoke_queries: list[str] = Field(default_factory=list)
    minimum_expected_documents: int = 1
    loader_strategy: str | None = None
    row_source_strategy: str | None = None
    row_source_endpoint: str | None = None
    row_source_module: str | None = None
    row_source_callable: str | None = None
    row_id_field: str | None = None
    row_image_url_field: str | None = None
    pagination_strategy: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "corpus",
        "chunking_strategy",
        "collection_alias",
        "build_collection",
        "loader_strategy",
        "row_source_strategy",
        "row_source_endpoint",
        "row_source_module",
        "row_source_callable",
        "row_id_field",
        "row_image_url_field",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        return _normalize_optional_text(value)


class RetrievalIndexPlan(BaseModel):
    site_id: str
    site_slug: str
    corpora: list[RagCorpusPlan] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("site_id", "site_slug", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class IntegrationPlan(BaseModel):
    host_backend: HostBackendPlan
    host_frontend: HostFrontendPlan
    chatbot_bridge: ChatbotBridgePlan
    retrieval_index_plan: RetrievalIndexPlan | None = None
    capability_upgrade: dict[str, Any] = Field(default_factory=dict)
    planning_notes: PlanningNotes = Field(default_factory=PlanningNotes)

    model_config = ConfigDict(extra="forbid")

    @property
    def backend_wiring(self) -> HostBackendPlan:
        return self.host_backend

    @property
    def frontend_integration(self) -> HostFrontendPlan:
        return self.host_frontend


class GoalMaterialization(BaseModel):
    capabilities: list[str] = Field(default_factory=list)
    owner: str = "deterministic"
    rationale: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PlanningCoverageReport(BaseModel):
    covered: bool
    required_capabilities: list[str] = Field(default_factory=list)
    covered_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class StrategyCandidate(BaseModel):
    candidate_id: str
    layer: str
    strategy: str
    summary: str
    tradeoffs: list[str] = Field(default_factory=list)
    supported: bool = True
    selected: bool = False
    confidence: float | None = None
    owner: str = "llm"

    model_config = ConfigDict(extra="forbid")

    @field_validator("candidate_id", "layer", "strategy", "summary", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class RepairHint(BaseModel):
    code: str
    rewind_to: str
    reason: str
    trigger_conditions: list[str] = Field(default_factory=list)
    owner: str = "deterministic"

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", "rewind_to", "reason", "owner", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _normalize_text(value)


class PlanningBundle(BaseModel):
    goal_materialization: GoalMaterialization = Field(default_factory=GoalMaterialization)
    coverage_report: PlanningCoverageReport
    strategy_candidates: list[StrategyCandidate] = Field(default_factory=list)
    integration_strategy: IntegrationStrategy
    target_bindings: list[TargetBinding] = Field(default_factory=list)
    operation_ir: list[PlannedOperation] = Field(default_factory=list)
    validation_plan: list[PlannedValidation] = Field(default_factory=list)
    risk_register: list[PlanningRisk] = Field(default_factory=list)
    repair_hints: list[RepairHint] = Field(default_factory=list)
    retrieval_index_plan: RetrievalIndexPlan | None = None
    capability_upgrade: dict[str, Any] = Field(default_factory=dict)
    integration_plan: IntegrationPlan

    model_config = ConfigDict(extra="forbid")


# Backward-compatible aliases for transitional code paths.
BackendWiringPlan = HostBackendPlan
FrontendIntegrationPlan = HostFrontendPlan
