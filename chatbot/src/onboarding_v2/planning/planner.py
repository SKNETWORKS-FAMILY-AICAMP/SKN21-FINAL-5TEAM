from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from chatbot.src.onboarding_v2.eventing import EventCallback
from chatbot.src.onboarding_v2.llm_runtime import invoke_structured_stage
from chatbot.src.onboarding_v2.models.analysis import (
    AnalysisBundle,
    AnalysisGraph,
    AnalysisSnapshot,
    CandidateSet,
    ContractRecord,
    DomainIntegration,
    FrameworkProfile,
    RagSources,
    RetrievalPlan,
    VerifiedContracts,
    WorkspaceProfile,
)
from chatbot.src.onboarding_v2.models.common import ArtifactRef, PathCandidate
from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    GoalMaterialization,
    HostBackendPlan,
    HostFrontendPlan,
    IntegrationPlan,
    IntegrationStrategy,
    PlannedOperation,
    PlannedValidation,
    PlanningBundle,
    PlanningCoverageReport,
    PlanningNotes,
    PlanningRisk,
    RagCorpusPlan,
    RepairHint,
    ResolvedAuthContract,
    ResolvedOrderActionContract,
    ResolvedRequestFieldContract,
    ResolvedResponseContract,
    RetrievalIndexPlan,
    StrategyCandidate,
    TargetBinding,
)
from chatbot.src.onboarding_v2.storage import DebugStore, LlmUsageStore

SUPPORTED_ORDER_TOOLS = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]

DEFAULT_GOAL_CAPABILITIES = [
    "auth_bootstrap",
    "order_lookup",
    "order_action",
    "frontend_widget_mount",
    "chatbot_adapter_setup",
]

DEFAULT_AVAILABLE_ADAPTERS = {
    "django_project_urlconf_import_view",
    "flask_app_register_blueprint",
    "fastapi_include_router",
    "react_app_shell_outside_routes",
    "react_api_client_augment_existing",
    "generated_adapter_package",
}

_STRATEGY_PROMPT = """You are the planning strategy synthesizer for onboarding_v2.
Return JSON with one key:
- strategy_candidates: array of objects with candidate_id, layer, strategy, summary, tradeoffs, supported, selected, confidence, owner

Rules:
- Suggest concrete compiler-facing strategies only.
- Prefer supported strategies for the detected frameworks.
- Mark only one candidate per layer as selected.
- Do not invent unsupported compiler strategy names.
- Do not include markdown."""

_BINDING_PROMPT = """You are the planning binding selector for onboarding_v2.
Return JSON with one key:
- target_bindings: array of objects with capability, target_path, selection_reason, selection_mode, evidence_refs

Rules:
- Use only verified analysis facts and candidate paths.
- Never invent files.
- Prefer verified order/auth files over generic candidates.
- Do not include markdown."""

_RISK_PROMPT = """You are the planning risk analyzer for onboarding_v2.
Return JSON with one key:
- risk_register: array of objects with code, summary, severity, owner, mitigations

Rules:
- Mention only concrete failure modes supported by the analysis input.
- Keep risks concise and actionable.
- Do not include markdown."""

_REPAIR_HINT_PROMPT = """You are the planning repair hint generator for onboarding_v2.
Return JSON with one key:
- repair_hints: array of objects with code, rewind_to, reason, trigger_conditions, owner

Rules:
- rewind_to must be one of analysis, planning, validation.
- Use analysis for missing facts, planning for unsupported strategies/binding drift, validation for runtime mismatches.
- Do not include markdown."""

_RISK_AND_REPAIR_PROMPT = """You are the planning risk and repair analyzer for onboarding_v2.
Return JSON with two keys:
- risk_register: array of objects with code, summary, severity, owner, mitigations
- repair_hints: array of objects with code, rewind_to, reason, trigger_conditions, owner

Rules:
- Mention only concrete failure modes supported by the analysis input.
- Keep risks concise and actionable.
- rewind_to must be one of analysis, planning, validation.
- Use analysis for missing facts, planning for unsupported strategies/binding drift, validation for runtime mismatches.
- Do not include markdown."""


class _StrategyEnvelope(BaseModel):
    strategy_candidates: list[StrategyCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _BindingEnvelope(BaseModel):
    target_bindings: list[TargetBinding] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _RiskEnvelope(BaseModel):
    risk_register: list[PlanningRisk] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _RepairEnvelope(BaseModel):
    repair_hints: list[RepairHint] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _RiskAndRepairEnvelope(BaseModel):
    risk_register: list[PlanningRisk] = Field(default_factory=list)
    repair_hints: list[RepairHint] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def build_planning_bundle(
    *,
    snapshot: AnalysisSnapshot,
    chatbot_server_base_url: str,
    analysis_bundle: AnalysisBundle | None = None,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini",
    llm_builder: Callable[[str, str, float], Any] | None = None,
    debug_store: DebugStore | None = None,
    usage_store: LlmUsageStore | None = None,
    attempt: int = 1,
    available_adapters: set[str] | None = None,
    validation_capabilities: list[str] | None = None,
    strict_coverage: bool = True,
    artifact_refs: list[ArtifactRef] | None = None,
    event_callback: EventCallback | None = None,
    heartbeat_interval_s: float = 5.0,
) -> PlanningBundle:
    if analysis_bundle is None:
        raise ValueError("analysis_bundle is required for onboarding_v2 planning")
    bundle = analysis_bundle
    adapters = set(available_adapters or DEFAULT_AVAILABLE_ADAPTERS)
    goal_materialization = _build_goal_materialization()
    coverage_report = _build_coverage_report(
        goal_materialization=goal_materialization,
        analysis_bundle=bundle,
    )
    if strict_coverage and not coverage_report.covered:
        missing = ", ".join(coverage_report.missing_capabilities) or "unknown"
        raise ValueError(f"analysis coverage incomplete for planning: {missing}")

    strategy_fallback = _build_strategy_candidates_fallback(
        framework_profile=bundle.framework_profile,
        available_adapters=adapters,
    )
    strategy_response = invoke_structured_stage(
        stage="planning",
        phase="strategy-synthesis",
        provider=llm_provider,
        model=llm_model,
        system_prompt=_STRATEGY_PROMPT,
        payload={
            "framework_profile": bundle.framework_profile.model_dump(mode="json"),
            "analysis_graph": bundle.analysis_graph.model_dump(mode="json"),
            "verified_contracts": bundle.verified_contracts.model_dump(mode="json"),
            "available_adapters": sorted(adapters),
        },
        response_model=_StrategyEnvelope,
        fallback_payload={
            "strategy_candidates": [item.model_dump(mode="json") for item in strategy_fallback]
        },
        attempt=attempt,
        debug_store=debug_store,
        usage_store=usage_store,
        llm_builder=llm_builder,
        artifact_refs=artifact_refs,
        event_callback=event_callback,
        heartbeat_interval_s=heartbeat_interval_s,
    )
    strategy_candidates = _feasibility_filter(
        candidates=strategy_response.strategy_candidates or strategy_fallback,
        available_adapters=adapters,
        framework_profile=bundle.framework_profile,
    )

    integration_strategy = _select_integration_strategy(
        strategy_candidates=strategy_candidates,
        framework_profile=bundle.framework_profile,
    )

    binding_fallback = _build_target_bindings_fallback(bundle=bundle)
    binding_response = invoke_structured_stage(
        stage="planning",
        phase="binding-selection",
        provider=llm_provider,
        model=llm_model,
        system_prompt=_BINDING_PROMPT,
        payload={
            "integration_strategy": integration_strategy.model_dump(mode="json"),
            "analysis_graph": bundle.analysis_graph.model_dump(mode="json"),
            "verified_contracts": bundle.verified_contracts.model_dump(mode="json"),
            "candidate_set": bundle.candidate_set.model_dump(mode="json"),
        },
        response_model=_BindingEnvelope,
        fallback_payload={
            "target_bindings": [item.model_dump(mode="json") for item in binding_fallback]
        },
        attempt=attempt,
        debug_store=debug_store,
        usage_store=usage_store,
        llm_builder=llm_builder,
        artifact_refs=artifact_refs,
        event_callback=event_callback,
        heartbeat_interval_s=heartbeat_interval_s,
    )
    target_bindings = _sanitize_target_bindings(
        requested=binding_response.target_bindings,
        fallback=binding_fallback,
        analysis_bundle=bundle,
    )

    operation_ir = _build_operation_ir(
        integration_strategy=integration_strategy,
        target_bindings=target_bindings,
    )
    validation_plan = _build_validation_plan(
        integration_strategy=integration_strategy,
        target_bindings=target_bindings,
        validation_capabilities=validation_capabilities or [],
    )

    risk_fallback = _build_risk_register_fallback(
        analysis_bundle=bundle,
        strategy_candidates=strategy_candidates,
        coverage_report=coverage_report,
    )
    repair_fallback = _build_repair_hints_fallback(
        coverage_report=coverage_report,
        strategy_candidates=strategy_candidates,
        target_bindings=target_bindings,
    )
    risk_and_repair_response = invoke_structured_stage(
        stage="planning",
        phase="risk-and-repair",
        provider=llm_provider,
        model=llm_model,
        system_prompt=_RISK_AND_REPAIR_PROMPT,
        payload={
            "coverage_report": coverage_report.model_dump(mode="json"),
            "strategy_candidates": [item.model_dump(mode="json") for item in strategy_candidates],
            "target_bindings": [item.model_dump(mode="json") for item in target_bindings],
            "analysis_bundle": {
                "framework_profile": bundle.framework_profile.model_dump(mode="json"),
                "unresolved_ambiguities": bundle.unresolved_ambiguities,
            },
        },
        response_model=_RiskAndRepairEnvelope,
        fallback_payload={
            "risk_register": [item.model_dump(mode="json") for item in risk_fallback],
            "repair_hints": [item.model_dump(mode="json") for item in repair_fallback],
        },
        attempt=attempt,
        debug_store=debug_store,
        usage_store=usage_store,
        llm_builder=llm_builder,
        artifact_refs=artifact_refs,
        event_callback=event_callback,
        heartbeat_interval_s=heartbeat_interval_s,
    )
    risk_register = _dedupe_risks(risk_and_repair_response.risk_register or risk_fallback)
    repair_hints = _dedupe_repair_hints(risk_and_repair_response.repair_hints or repair_fallback)
    retrieval_index_plan = _build_retrieval_index_plan(
        site_id=_resolve_site_id(snapshot),
        rag_sources=bundle.rag_sources,
        run_id="runtime",
        product_search_endpoint=str(snapshot.domain_integration.product_search_endpoint or ""),
    )
    capability_upgrade = _build_capability_upgrade(
        rag_sources=bundle.rag_sources,
        retrieval_index_plan=retrieval_index_plan,
    )

    integration_plan = _derive_integration_plan(
        snapshot=snapshot,
        analysis_bundle=bundle,
        integration_strategy=integration_strategy,
        target_bindings=target_bindings,
        chatbot_server_base_url=chatbot_server_base_url,
        coverage_report=coverage_report,
        risk_register=risk_register,
        retrieval_index_plan=retrieval_index_plan,
        capability_upgrade=capability_upgrade,
    )

    return PlanningBundle(
        goal_materialization=goal_materialization,
        coverage_report=coverage_report,
        strategy_candidates=strategy_candidates,
        integration_strategy=integration_strategy,
        target_bindings=target_bindings,
        operation_ir=operation_ir,
        validation_plan=validation_plan,
        risk_register=risk_register,
        repair_hints=repair_hints,
        retrieval_index_plan=retrieval_index_plan,
        capability_upgrade=capability_upgrade,
        integration_plan=integration_plan,
    )


def build_integration_plan(
    snapshot: AnalysisSnapshot,
    *,
    chatbot_server_base_url: str,
    analysis_bundle: AnalysisBundle | None = None,
    **kwargs: Any,
) -> IntegrationPlan:
    if analysis_bundle is None:
        raise ValueError("analysis_bundle is required for onboarding_v2 planning")
    if "strict_coverage" not in kwargs:
        kwargs["strict_coverage"] = False
    return build_planning_bundle(
        snapshot=snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url=chatbot_server_base_url,
        **kwargs,
    ).integration_plan


def _build_goal_materialization() -> GoalMaterialization:
    return GoalMaterialization(
        capabilities=list(DEFAULT_GOAL_CAPABILITIES),
        owner="deterministic",
        rationale=[
            "host auth bootstrap is required for authenticated chatbot operations",
            "order lookup and action bindings are required for order tools",
            "frontend widget mount is required for host UI integration",
            "chatbot adapter setup is required for generated tool routing",
        ],
    )


def _build_coverage_report(
    *,
    goal_materialization: GoalMaterialization,
    analysis_bundle: AnalysisBundle,
) -> PlanningCoverageReport:
    auth_bootstrap = any(
        record.identifier == "chat_auth_bootstrap"
        for record in analysis_bundle.verified_contracts.auth_components
    ) and bool(
        analysis_bundle.candidate_set.route_definitions
    )
    order_lookup = any(
        record.identifier == "order_lookup"
        for record in analysis_bundle.verified_contracts.tool_targets
    ) and any(
        "order" in record.identifier.lower()
        for record in analysis_bundle.verified_contracts.api_endpoints
    )
    order_action = any(
        record.identifier == "order_action"
        for record in analysis_bundle.verified_contracts.tool_targets
    ) and any(
        "order" in record.identifier.lower()
        for record in analysis_bundle.verified_contracts.api_endpoints
    )
    frontend_widget_mount = bool(
        analysis_bundle.candidate_set.app_shells
        or analysis_bundle.snapshot.frontend_seams.widget_mount_candidates
    )
    chatbot_adapter_setup = (_chatbot_source_root() / "adapters" / "setup.py").exists()

    coverage_map = {
        "auth_bootstrap": auth_bootstrap,
        "order_lookup": order_lookup,
        "order_action": order_action,
        "frontend_widget_mount": frontend_widget_mount,
        "chatbot_adapter_setup": chatbot_adapter_setup,
    }
    covered_capabilities = [
        capability
        for capability in goal_materialization.capabilities
        if coverage_map.get(capability, False)
    ]
    missing_capabilities = [
        capability
        for capability in goal_materialization.capabilities
        if capability not in covered_capabilities
    ]
    gaps = []
    if not auth_bootstrap:
        gaps.append("verified auth bootstrap contract missing")
    if not order_lookup:
        gaps.append("verified order lookup contract missing")
    if not order_action:
        gaps.append("verified order action contract missing")
    if not frontend_widget_mount:
        gaps.append("frontend mount boundary missing")
    if not chatbot_adapter_setup:
        gaps.append("chatbot adapter setup target missing")

    return PlanningCoverageReport(
        covered=not missing_capabilities,
        required_capabilities=list(goal_materialization.capabilities),
        covered_capabilities=covered_capabilities,
        missing_capabilities=missing_capabilities,
        gaps=gaps,
    )


def _build_strategy_candidates_fallback(
    *,
    framework_profile: FrameworkProfile,
    available_adapters: set[str],
) -> list[StrategyCandidate]:
    backend_strategy = {
        "django": "django_project_urlconf_import_view",
        "flask": "flask_app_register_blueprint",
        "fastapi": "fastapi_include_router",
    }.get(framework_profile.backend_framework, "django_project_urlconf_import_view")
    mount_strategy = "react_app_shell_outside_routes"
    api_strategy = "react_api_client_augment_existing"
    candidates = [
        StrategyCandidate(
            candidate_id=f"backend-{framework_profile.backend_framework}-route",
            layer="backend",
            strategy=backend_strategy,
            summary="use framework-native route registration adapter",
            tradeoffs=["stable compiler support", "works best when route entrypoint is verified"],
            supported=backend_strategy in available_adapters,
            selected=backend_strategy in available_adapters,
            confidence=0.92,
            owner="deterministic",
        ),
        StrategyCandidate(
            candidate_id=f"backend-{framework_profile.backend_framework}-service-bridge",
            layer="backend",
            strategy="service_layer_bridge_insert",
            summary="insert chatbot bridge deeper in the service layer",
            tradeoffs=["potentially more precise", "unsupported by current compiler adapters"],
            supported=False,
            selected=False,
            confidence=0.44,
            owner="deterministic",
        ),
        StrategyCandidate(
            candidate_id=f"frontend-{framework_profile.frontend_framework}-mount",
            layer="frontend_mount",
            strategy=mount_strategy,
            summary="inject widget at the verified app shell boundary",
            tradeoffs=["uses existing compiler adapter", "generic for non-react host frameworks"],
            supported=mount_strategy in available_adapters,
            selected=mount_strategy in available_adapters,
            confidence=0.81,
            owner="deterministic",
        ),
        StrategyCandidate(
            candidate_id=f"frontend-{framework_profile.frontend_framework}-api",
            layer="frontend_api",
            strategy=api_strategy,
            summary="augment the existing frontend transport module",
            tradeoffs=["keeps one network abstraction", "generic adapter may need extra runtime validation"],
            supported=api_strategy in available_adapters,
            selected=api_strategy in available_adapters,
            confidence=0.83,
            owner="deterministic",
        ),
        StrategyCandidate(
            candidate_id="chatbot-generated-adapter",
            layer="chatbot_bridge",
            strategy="generated_adapter_package",
            summary="wire generated site adapter into chatbot setup",
            tradeoffs=["matches current chatbot compiler", "requires setup target to exist"],
            supported="generated_adapter_package" in available_adapters,
            selected="generated_adapter_package" in available_adapters,
            confidence=0.95,
            owner="deterministic",
        ),
    ]
    return candidates


def _feasibility_filter(
    *,
    candidates: list[StrategyCandidate],
    available_adapters: set[str],
    framework_profile: FrameworkProfile,
) -> list[StrategyCandidate]:
    del framework_profile
    filtered: list[StrategyCandidate] = []
    selected_by_layer: set[str] = set()
    for candidate in candidates:
        supported = candidate.strategy in available_adapters
        selected = candidate.selected and supported and candidate.layer not in selected_by_layer
        if selected:
            selected_by_layer.add(candidate.layer)
        filtered.append(candidate.model_copy(update={"supported": supported, "selected": selected}))
    for candidate in filtered:
        if candidate.layer in selected_by_layer or not candidate.supported:
            continue
        filtered[filtered.index(candidate)] = candidate.model_copy(update={"selected": True})
        selected_by_layer.add(candidate.layer)
    return filtered


def _select_integration_strategy(
    *,
    strategy_candidates: list[StrategyCandidate],
    framework_profile: FrameworkProfile,
) -> IntegrationStrategy:
    by_layer = {
        candidate.layer: candidate.strategy
        for candidate in strategy_candidates
        if candidate.selected and candidate.supported
    }
    return IntegrationStrategy(
        backend_strategy=by_layer.get(
            "backend",
            {
                "django": "django_project_urlconf_import_view",
                "flask": "flask_app_register_blueprint",
                "fastapi": "fastapi_include_router",
            }.get(framework_profile.backend_framework, "django_project_urlconf_import_view"),
        ),
        frontend_mount_strategy=by_layer.get("frontend_mount", "react_app_shell_outside_routes"),
        frontend_api_strategy=by_layer.get("frontend_api", "react_api_client_augment_existing"),
        chatbot_bridge_strategy=by_layer.get("chatbot_bridge", "generated_adapter_package"),
        owner="llm" if any(candidate.owner == "llm" and candidate.selected for candidate in strategy_candidates) else "deterministic",
    )


def _build_target_bindings_fallback(*, bundle: AnalysisBundle) -> list[TargetBinding]:
    auth_record = _select_auth_bridge_contract(bundle.verified_contracts.auth_components)
    lookup_record = _find_contract(bundle.verified_contracts.tool_targets, "order_lookup")
    action_record = _find_contract(bundle.verified_contracts.tool_targets, "order_action")
    route_target = _path_or_default(bundle.candidate_set.route_definitions, default="backend/foodshop/urls.py")
    mount_target = _path_or_default(bundle.candidate_set.app_shells, default="frontend/src/App.js")
    api_target = _path_or_default(bundle.candidate_set.api_clients, default=mount_target)
    chatbot_setup = "src/adapters/setup.py"
    return [
        TargetBinding(
            capability="route_registration",
            target_path=route_target,
            selection_reason="verified backend route registration point",
            selection_mode="deterministic",
            evidence_refs=[route_target],
        ),
        TargetBinding(
            capability="auth_bridge",
            target_path=auth_record.location if auth_record else route_target,
            selection_reason="verified auth bootstrap source",
            selection_mode="deterministic",
            evidence_refs=list(auth_record.evidence_refs if auth_record else [route_target]),
        ),
        TargetBinding(
            capability="order_lookup",
            target_path=lookup_record.location if lookup_record else _path_or_default(bundle.candidate_set.order_targets, default="backend/orders/views.py"),
            selection_reason="verified order lookup tool target",
            selection_mode="deterministic",
            evidence_refs=list(lookup_record.evidence_refs if lookup_record else []),
        ),
        TargetBinding(
            capability="order_action",
            target_path=action_record.location if action_record else _path_or_default(bundle.candidate_set.order_targets, default="backend/orders/views.py"),
            selection_reason="verified order action tool target",
            selection_mode="deterministic",
            evidence_refs=list(action_record.evidence_refs if action_record else []),
        ),
        TargetBinding(
            capability="frontend_mount",
            target_path=mount_target,
            selection_reason="verified frontend app shell mount boundary",
            selection_mode="deterministic",
            evidence_refs=[mount_target],
        ),
        TargetBinding(
            capability="api_client",
            target_path=api_target,
            selection_reason="verified frontend API transport target",
            selection_mode="deterministic",
            evidence_refs=[api_target],
        ),
        TargetBinding(
            capability="chatbot_setup",
            target_path=chatbot_setup,
            selection_reason="generated chatbot adapter setup target",
            selection_mode="deterministic",
            evidence_refs=[chatbot_setup],
        ),
    ]


def _sanitize_target_bindings(
    *,
    requested: list[TargetBinding],
    fallback: list[TargetBinding],
    analysis_bundle: AnalysisBundle,
) -> list[TargetBinding]:
    allowed_paths = {
        candidate.path
        for candidate in [
            *analysis_bundle.candidate_set.route_definitions,
            *analysis_bundle.candidate_set.auth_components,
            *analysis_bundle.candidate_set.order_targets,
            *analysis_bundle.candidate_set.app_shells,
            *analysis_bundle.candidate_set.api_clients,
        ]
    }
    allowed_paths.update(binding.target_path for binding in fallback if binding.target_path)
    allowed_paths.add("src/adapters/setup.py")
    bindings: list[TargetBinding] = []
    seen: set[str] = set()
    for binding in [*requested, *fallback]:
        if binding.capability in seen:
            continue
        if binding.target_path not in allowed_paths:
            continue
        seen.add(binding.capability)
        bindings.append(binding)
    return bindings


def _build_operation_ir(
    *,
    integration_strategy: IntegrationStrategy,
    target_bindings: list[TargetBinding],
) -> list[PlannedOperation]:
    binding_map = {binding.capability: binding for binding in target_bindings}
    return [
        PlannedOperation(
            operation="add_backend_auth_bridge",
            stage="backend",
            target_path=binding_map["auth_bridge"].target_path,
            strategy=integration_strategy.backend_strategy,
        ),
        PlannedOperation(
            operation="register_route",
            stage="backend",
            target_path=binding_map["route_registration"].target_path,
            strategy=integration_strategy.backend_strategy,
            depends_on=["add_backend_auth_bridge"],
        ),
        PlannedOperation(
            operation="augment_order_lookup_handler",
            stage="backend",
            target_path=binding_map["order_lookup"].target_path,
            strategy="augment_existing_order_action_endpoint",
        ),
        PlannedOperation(
            operation="augment_order_action_handler",
            stage="backend",
            target_path=binding_map["order_action"].target_path,
            strategy="augment_existing_order_action_endpoint",
        ),
        PlannedOperation(
            operation="inject_frontend_widget_mount",
            stage="frontend",
            target_path=binding_map["frontend_mount"].target_path,
            strategy=integration_strategy.frontend_mount_strategy,
        ),
        PlannedOperation(
            operation="augment_frontend_api_client",
            stage="frontend",
            target_path=binding_map["api_client"].target_path,
            strategy=integration_strategy.frontend_api_strategy,
        ),
        PlannedOperation(
            operation="register_chatbot_adapter",
            stage="chatbot",
            target_path=binding_map["chatbot_setup"].target_path,
            strategy=integration_strategy.chatbot_bridge_strategy,
        ),
    ]


def _build_validation_plan(
    *,
    integration_strategy: IntegrationStrategy,
    target_bindings: list[TargetBinding],
    validation_capabilities: list[str],
) -> list[PlannedValidation]:
    del integration_strategy
    binding_map = {binding.capability: binding for binding in target_bindings}
    validations = [
        PlannedValidation(
            name="auth_bootstrap_contract",
            kind="http_contract",
            target="/api/chat/auth-token",
            success_signal="bootstrap endpoint returns authenticated/access_token payload",
        ),
        PlannedValidation(
            name="order_lookup_contract",
            kind="backend_probe",
            target=binding_map["order_lookup"].target_path,
            success_signal="lookup tool reaches host order query path",
        ),
        PlannedValidation(
            name="order_action_contract",
            kind="backend_probe",
            target=binding_map["order_action"].target_path,
            success_signal="cancel/refund/exchange tools reach host mutation path",
        ),
        PlannedValidation(
            name="widget_order_e2e",
            kind="frontend_e2e" if "frontend_e2e" in validation_capabilities or not validation_capabilities else "frontend_probe",
            target=binding_map["frontend_mount"].target_path,
            success_signal="shared chatbot widget mounts and order flow succeeds",
        ),
    ]
    return validations


def _build_risk_register_fallback(
    *,
    analysis_bundle: AnalysisBundle,
    strategy_candidates: list[StrategyCandidate],
    coverage_report: PlanningCoverageReport,
) -> list[PlanningRisk]:
    risks: list[PlanningRisk] = []
    for question in analysis_bundle.unresolved_ambiguities:
        if question == "multiple frontend app shell candidates detected":
            risks.append(
                PlanningRisk(
                    code="app_shell_ambiguity",
                    summary="multiple frontend app shell candidates require mount validation",
                    mitigations=["prefer source app shells over built artifacts", "run widget mount smoke after apply"],
                )
            )
        if question == "multiple router boundary candidates detected":
            risks.append(
                PlanningRisk(
                    code="router_boundary_ambiguity",
                    summary="multiple router boundary candidates may redirect widget injection to the wrong layer",
                    mitigations=["prefer source router files", "run frontend route smoke and widget e2e"],
                )
            )
    if coverage_report.missing_capabilities:
        risks.append(
            PlanningRisk(
                code="coverage_incomplete",
                summary="analysis coverage is incomplete for at least one required capability",
                severity="high",
                mitigations=["rewind to analysis and expand retrieval/evidence verification"],
            )
        )
    if any(not candidate.supported for candidate in strategy_candidates):
        risks.append(
            PlanningRisk(
                code="unsupported_strategy_candidates_present",
                summary="some synthesized strategies are not supported by the active compiler adapter set",
                mitigations=["keep only compiler-backed strategies", "replan if binding drift forces unsupported adapters"],
            )
        )
    if analysis_bundle.framework_profile.frontend_framework in {"vue", "next"}:
        risks.append(
            PlanningRisk(
                code="generic_frontend_adapter",
                summary="frontend compile path relies on a generic mount/api adapter for a non-react host",
                mitigations=["validate widget mount at runtime", "replan if host structure diverges from generic adapter assumptions"],
            )
        )
    return _dedupe_risks(risks)


def _build_repair_hints_fallback(
    *,
    coverage_report: PlanningCoverageReport,
    strategy_candidates: list[StrategyCandidate],
    target_bindings: list[TargetBinding],
) -> list[RepairHint]:
    hints: list[RepairHint] = []
    if coverage_report.missing_capabilities:
        hints.append(
            RepairHint(
                code="missing_verified_contracts",
                rewind_to="analysis",
                reason="required verified contracts are missing from analyzer output",
                trigger_conditions=["coverage_failed"],
            )
        )
    if any(not candidate.supported for candidate in strategy_candidates):
        hints.append(
            RepairHint(
                code="unsupported_strategy_binding",
                rewind_to="planning",
                reason="planner produced or considered strategies outside compiler support",
                trigger_conditions=["unsupported_strategy_selected", "binding_drift"],
            )
        )
    if target_bindings:
        hints.append(
            RepairHint(
                code="runtime_validation_mismatch",
                rewind_to="validation",
                reason="expected runtime mismatches should rerun validation before replanning",
                trigger_conditions=["http_contract_failed", "frontend_mount_smoke_failed"],
            )
        )
    return _dedupe_repair_hints(hints)


def _derive_integration_plan(
    *,
    snapshot: AnalysisSnapshot,
    analysis_bundle: AnalysisBundle,
    integration_strategy: IntegrationStrategy,
    target_bindings: list[TargetBinding],
    chatbot_server_base_url: str,
    coverage_report: PlanningCoverageReport,
    risk_register: list[PlanningRisk],
    retrieval_index_plan: RetrievalIndexPlan,
    capability_upgrade: dict[str, Any],
) -> IntegrationPlan:
    del coverage_report
    binding_map = {binding.capability: binding for binding in target_bindings}
    site_id = _resolve_site_id(snapshot)
    normalized_chatbot_server_base_url = str(chatbot_server_base_url or "").strip().rstrip("/")
    if not normalized_chatbot_server_base_url:
        raise ValueError("chatbot_server_base_url is required for V2 dual-patch planning")
    route_target = binding_map["route_registration"].target_path
    auth_source = binding_map["auth_bridge"].target_path
    mount_target = binding_map["frontend_mount"].target_path
    api_client_target = binding_map["api_client"].target_path
    order_lookup_target = binding_map["order_lookup"].target_path
    order_action_target = binding_map["order_action"].target_path
    bridge_contract = _derive_chatbot_bridge_contract(
        domain_integration=analysis_bundle.snapshot.domain_integration,
        site_id=site_id,
        source_root=Path(snapshot.repo_profile.source_root),
        backend_framework=analysis_bundle.framework_profile.backend_framework,
        auth_handler_source=auth_source,
        auth_style_hint=str(snapshot.repo_profile.auth_style or ""),
        order_lookup_target=order_lookup_target,
    )
    assumptions = [
        "planner consumed verified analysis graph and deterministic compiler capabilities",
        "host auth bootstrap returns access_token payload for chatbot adapter validation",
    ]
    if analysis_bundle.framework_profile.backend_framework == "django":
        assumptions.append("chat auth bridge will be materialized in backend/chat_auth.py")
    if mount_target == api_client_target:
        assumptions.append("frontend api support falls back to app shell because no dedicated api client was verified")

    return IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy=integration_strategy.backend_strategy,
            route_target=route_target,
            import_target=route_target,
            login_endpoint=_derive_host_login_endpoint(analysis_bundle.snapshot.domain_integration),
            order_lookup_target=order_lookup_target,
            order_action_target=order_action_target,
            exchange_strategy=_choose_exchange_strategy(
                site_id=site_id,
                order_action_target=order_action_target,
                domain_integration=analysis_bundle.snapshot.domain_integration,
            ),
            order_action_request_field=bridge_contract["request_field_mappings"]["action"],
            order_action_reason_field=bridge_contract["request_field_mappings"]["reason"],
            order_action_new_option_field=bridge_contract["request_field_mappings"]["new_option_id"],
            order_action_response_serializer="serialize_order",
            exchange_status_transition="EXCHANGE_REQUESTED",
            supported_order_tools=list(bridge_contract["order_action_contract"].supported_actions),
            auth_handler_source=auth_source,
            generated_handler_path=_choose_generated_handler_path(analysis_bundle.framework_profile.backend_framework),
            chat_auth_contract_path="/api/chat/auth-token",
            site_id=site_id,
            capability_profile="order_cs_only",
            enabled_retrieval_corpora=[],
            widget_features={"image_upload": False},
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy=integration_strategy.frontend_mount_strategy,
            mount_target=mount_target,
            router_boundary=_path_or_default(
                analysis_bundle.candidate_set.router_boundaries,
                default=mount_target,
            ),
            api_strategy=integration_strategy.frontend_api_strategy,
            api_client_target=api_client_target,
            auth_bootstrap_path="/api/chat/auth-token",
            chatbot_server_base_url=normalized_chatbot_server_base_url,
            chatbot_server_base_url_expression=_resolve_chatbot_server_base_url_expression(
                source_root=Path(snapshot.repo_profile.source_root),
                runtime_base_url=normalized_chatbot_server_base_url,
            ),
            capability_profile="order_cs_only",
            enabled_retrieval_corpora=[],
            widget_features={"image_upload": False},
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key=_normalize_site_key(site_id),
            adapter_package=f"src/adapters/generated/{_normalize_site_key(site_id)}",
            setup_target=binding_map["chatbot_setup"].target_path,
            host_base_url_env_var=_build_chatbot_bridge_env_var(site_id),
            auth_validation_endpoint=bridge_contract["auth_validation_endpoint"],
            current_user_endpoint=bridge_contract["current_user_endpoint"],
            product_search_endpoint=bridge_contract["product_search_endpoint"],
            order_list_endpoint=bridge_contract["order_list_endpoint"],
            order_detail_endpoint=bridge_contract["order_detail_endpoint"],
            order_action_endpoint=bridge_contract["order_action_endpoint"],
            order_action_endpoints=bridge_contract["order_action_endpoints"],
            auth_contract=bridge_contract["auth_contract"],
            response_contract=bridge_contract["response_contract"],
            order_action_contract=bridge_contract["order_action_contract"],
            response_mapping_profile=bridge_contract["response_mapping_profile"],
            request_field_mappings=bridge_contract["request_field_mappings"],
            supported_tools=list(bridge_contract["order_action_contract"].supported_actions),
        ),
        retrieval_index_plan=retrieval_index_plan,
        capability_upgrade=capability_upgrade,
        planning_notes=PlanningNotes(
            assumptions=assumptions,
            ambiguities=list(analysis_bundle.unresolved_ambiguities),
            llm_rationale=[risk.summary for risk in risk_register if risk.owner == "llm"],
        ),
    )


def _find_contract(records: list[ContractRecord], identifier: str) -> ContractRecord | None:
    return next((record for record in records if record.identifier == identifier), None)


def _select_auth_bridge_contract(records: list[ContractRecord]) -> ContractRecord | None:
    ranked_matches: list[tuple[int, int, ContractRecord]] = []
    for index, record in enumerate(records):
        if record.identifier != "chat_auth_bootstrap":
            continue
        role = str(record.details.get("role", "")).strip().lower()
        if record.kind == "auth_component" and role == "backend_auth_source":
            priority = 0
        elif record.kind == "auth_component":
            priority = 1
        elif record.kind == "authz_guard":
            priority = 2
        else:
            priority = 3
        ranked_matches.append((priority, index, record))
    if not ranked_matches:
        return None
    ranked_matches.sort(key=lambda item: (item[0], item[1]))
    return ranked_matches[0][2]


def _path_or_default(candidates: list[PathCandidate], *, default: str) -> str:
    for candidate in candidates:
        if candidate.path:
            return candidate.path
    return default


def _choose_order_target_from_candidates(
    candidates: list[PathCandidate],
    *,
    role: str,
    default: str,
) -> str:
    valid_candidates = [
        candidate
        for candidate in candidates
        if _is_valid_order_bridge_candidate(candidate.path)
    ]
    if not valid_candidates:
        return default
    ranked = sorted(
        enumerate(valid_candidates),
        key=lambda item: (
            -_order_target_role_score(item[1].path, role=role),
            item[0],
            item[1].path,
        ),
    )
    if _order_target_role_score(ranked[0][1].path, role=role) > 0:
        return ranked[0][1].path
    return valid_candidates[0].path


def _is_valid_order_bridge_candidate(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lower()
    if normalized.endswith("/urls.py") or normalized.endswith("/tests.py"):
        return False
    parts = Path(normalized).parts
    if "tests" in parts or "migrations" in parts:
        return False
    return True


def _order_target_role_score(path: str, *, role: str) -> int:
    normalized = path.lower()
    if role == "lookup":
        keywords = ("lookup", "status", "list", "detail", "query", "read")
    else:
        keywords = ("action", "update", "cancel", "refund", "exchange", "modify", "mutat", "command", "handler", "write")
    return 1 if any(keyword in normalized for keyword in keywords) else 0


def _chatbot_source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dedupe_candidates(items: list[PathCandidate]) -> list[PathCandidate]:
    seen: set[str] = set()
    deduped: list[PathCandidate] = []
    for item in items:
        if not item.path or item.path in seen:
            continue
        seen.add(item.path)
        deduped.append(item)
    return deduped


def _dedupe_risks(items: list[PlanningRisk]) -> list[PlanningRisk]:
    seen: set[str] = set()
    deduped: list[PlanningRisk] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        deduped.append(item)
    return deduped


def _dedupe_repair_hints(items: list[RepairHint]) -> list[RepairHint]:
    seen: set[str] = set()
    deduped: list[RepairHint] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        deduped.append(item)
    return deduped


def _choose_exchange_strategy(
    *,
    site_id: str,
    order_action_target: str,
    domain_integration: DomainIntegration,
) -> str:
    del site_id, order_action_target
    if domain_integration.order_action_endpoints:
        return "reuse_existing_order_action_endpoint"
    return "augment_existing_order_action_endpoint"


def _choose_generated_handler_path(backend_framework: str) -> str | None:
    if backend_framework in {"django", "flask"}:
        return "backend/chat_auth.py"
    if backend_framework == "fastapi":
        return "chat_auth.py"
    return None


def _normalize_site_key(site_id: str) -> str:
    cleaned = site_id.strip().lower().replace(" ", "_")
    return "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in cleaned)


def _build_retrieval_index_plan(
    *,
    site_id: str,
    rag_sources: RagSources,
    run_id: str,
    product_search_endpoint: str,
) -> RetrievalIndexPlan:
    site_slug = _normalize_site_key(site_id)
    corpora: list[RagCorpusPlan] = []
    corpus_specs = {
        "faq": ("qa_level", rag_sources.faq, ["배송은 얼마나 걸리나요?"], "faq_source_scan"),
        "policy": ("heading_sections", rag_sources.policy, ["환불 규정"], "policy_source_scan"),
        "discovery_image": ("entity_level", rag_sources.discovery_image, ["검은색 자켓"], "public_url_fetch"),
    }
    for corpus, (chunking_strategy, records, smoke_queries, default_loader) in corpus_specs.items():
        if not records:
            continue
        loader_strategy = _resolve_loader_strategy(
            corpus=corpus,
            records=records,
            default_loader=default_loader,
        )
        corpora.append(
            _build_rag_corpus_plan(
                corpus=corpus,
                chunking_strategy=chunking_strategy,
                collection_alias=f"site_{site_slug}__{corpus}",
                build_collection=f"site_{site_slug}__{corpus}__run_{run_id}",
                records=records,
                smoke_queries=smoke_queries,
                loader_strategy=loader_strategy,
                product_search_endpoint=product_search_endpoint,
            )
        )
    return RetrievalIndexPlan(site_id=site_id, site_slug=site_slug, corpora=corpora)


def _build_rag_corpus_plan(
    *,
    corpus: str,
    chunking_strategy: str,
    collection_alias: str,
    build_collection: str,
    records: list[Any],
    smoke_queries: list[str],
    loader_strategy: str,
    product_search_endpoint: str,
) -> RagCorpusPlan:
    faq_row_source_strategy = None
    faq_row_source_module = None
    faq_row_source_callable = None
    if corpus == "faq":
        faq_row_source_strategy, faq_row_source_module, faq_row_source_callable = _resolve_faq_row_source(
            records=records,
        )

    if corpus != "discovery_image":
        return RagCorpusPlan(
            corpus=corpus,
            enabled=True,
            chunking_strategy=chunking_strategy,
            collection_alias=collection_alias,
            build_collection=build_collection,
            sources=[record.path for record in records],
            smoke_queries=smoke_queries,
            minimum_expected_documents=1,
            loader_strategy=loader_strategy,
            row_source_strategy=faq_row_source_strategy,
            row_source_module=faq_row_source_module,
            row_source_callable=faq_row_source_callable,
        )

    image_field = next(
        (
            str((getattr(record, "details", {}) or {}).get("image_field") or "").strip()
            for record in records
            if str((getattr(record, "details", {}) or {}).get("image_field") or "").strip()
        ),
        "image_url",
    )
    return RagCorpusPlan(
        corpus=corpus,
        enabled=True,
        chunking_strategy=chunking_strategy,
        collection_alias=collection_alias,
        build_collection=build_collection,
        sources=[record.path for record in records],
        smoke_queries=smoke_queries,
        minimum_expected_documents=1,
        loader_strategy=loader_strategy,
        row_source_strategy="host_api_fetch",
        row_source_endpoint=product_search_endpoint,
        row_id_field="product_id",
        row_image_url_field=image_field or "image_url",
        pagination_strategy={
            "type": "page_number",
            "page_param": "page",
            "page_size_param": "page_size",
            "page_size": 100,
            "stop_on": "empty_or_repeated_ids",
        },
    )


def _resolve_loader_strategy(
    *,
    corpus: str,
    records: list[Any],
    default_loader: str,
) -> str:
    if corpus != "discovery_image":
        return default_loader

    discovered: list[str] = []
    for record in records:
        details = getattr(record, "details", {}) or {}
        candidates = details.get("loader_candidates") or []
        if isinstance(candidates, list):
            discovered.extend(str(item).strip() for item in candidates if str(item).strip())
        strategy = str(details.get("loader_strategy") or "").strip()
        if strategy:
            discovered.append(strategy)

    for candidate in ("public_url_fetch", "signed_url_resolver", "bucket_list_and_fetch"):
        if candidate in discovered:
            return candidate
    return default_loader


def _resolve_faq_row_source(
    *,
    records: list[Any],
) -> tuple[str, str | None, str | None]:
    for record in records:
        details = getattr(record, "details", {}) or {}
        strategy = str(details.get("row_source_strategy") or "").strip()
        module_name = str(details.get("row_source_module") or "").strip()
        callable_name = str(details.get("row_source_callable") or "").strip()
        if strategy == "host_python_fetch":
            return (
                "host_python_fetch",
                module_name or "models.faq",
                callable_name or "get_all_faq",
            )
        normalized_path = str(getattr(record, "path", "") or "").replace("\\", "/").lower()
        if normalized_path.endswith("backend/models/faq.py"):
            return ("host_python_fetch", "models.faq", "get_all_faq")
    return ("static_source_scan", None, None)


def _build_capability_upgrade(
    *,
    rag_sources: RagSources,
    retrieval_index_plan: RetrievalIndexPlan,
) -> dict[str, Any]:
    del rag_sources
    enabled_corpora = [item.corpus for item in retrieval_index_plan.corpora if item.enabled]
    profile = "order_cs_plus_retrieval" if enabled_corpora else "order_cs_only"
    return {
        "capability_profile": profile,
        "enabled_retrieval_corpora": enabled_corpora,
        "widget_features": {"image_upload": "discovery_image" in enabled_corpora},
    }


def _build_chatbot_bridge_env_var(site_id: str) -> str:
    normalized = _normalize_site_key(site_id).upper().replace("-", "_")
    return f"GENERATED_{normalized}_API_URL"


def _resolve_chatbot_server_base_url_expression(
    *,
    source_root: Path,
    runtime_base_url: str,
) -> str:
    package_path = source_root / "frontend" / "package.json"
    if not package_path.exists():
        if (source_root / "frontend" / "app").exists():
            return f'process.env.NEXT_PUBLIC_CHATBOT_SERVER_BASE_URL || "{_normalize_runtime_fallback(runtime_base_url)}"'
        raise ValueError("frontend/package.json is required to infer chatbotServerBaseUrl env injection strategy")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    dependencies = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    scripts = package.get("scripts") or {}
    combined_script_text = " ".join(str(value) for value in scripts.values())
    fallback = _normalize_runtime_fallback(runtime_base_url)

    if "react-scripts" in dependencies:
        return f'process.env.REACT_APP_CHATBOT_SERVER_BASE_URL || "{fallback}"'
    if "next" in dependencies:
        return f'process.env.NEXT_PUBLIC_CHATBOT_SERVER_BASE_URL || "{fallback}"'
    if "vite" in dependencies or "vite" in combined_script_text:
        return f'import.meta.env.VITE_CHATBOT_SERVER_BASE_URL || "{fallback}"'

    raise ValueError("unable to infer a safe chatbotServerBaseUrl env injection strategy for host frontend")


def _normalize_runtime_fallback(runtime_base_url: str) -> str:
    normalized = runtime_base_url.strip().rstrip("/")
    if normalized in {"http://localhost:8100", "http://127.0.0.1:8100"}:
        return "http://127.0.0.1:8100"
    return normalized


def _derive_chatbot_bridge_contract(
    *,
    domain_integration: DomainIntegration,
    site_id: str,
    source_root: Path,
    backend_framework: str,
    auth_handler_source: str,
    auth_style_hint: str,
    order_lookup_target: str | None = None,
) -> dict[str, Any]:
    login_endpoint = str(domain_integration.login_endpoint or "").strip()
    auth_validation_endpoint = str(
        domain_integration.auth_validation_endpoint or domain_integration.current_user_endpoint or ""
    ).strip()
    if not auth_validation_endpoint or auth_validation_endpoint == login_endpoint:
        auth_validation_endpoint = "/api/chat/auth-token"
    current_user_endpoint = str(domain_integration.current_user_endpoint or "").strip()
    if not current_user_endpoint or current_user_endpoint == login_endpoint:
        current_user_endpoint = auth_validation_endpoint
    product_search_endpoint = str(domain_integration.product_search_endpoint or "").strip()
    order_list_endpoint = str(domain_integration.order_list_endpoint or "").strip()
    order_detail_endpoint = str(domain_integration.order_detail_endpoint or "").strip()
    order_action_endpoint = str(domain_integration.order_action_endpoint or "").strip()
    order_action_endpoints = {
        str(action).strip(): str(path).strip()
        for action, path in (domain_integration.order_action_endpoints or {}).items()
        if str(action).strip() and str(path).strip()
    }

    missing = [
        name
        for name, value in {
            "auth_validation_endpoint": auth_validation_endpoint,
            "current_user_endpoint": current_user_endpoint,
            "product_search_endpoint": product_search_endpoint,
            "order_list_endpoint": order_list_endpoint,
            "order_detail_endpoint": order_detail_endpoint,
        }.items()
        if not value
    ]
    if not order_action_endpoint and not order_action_endpoints:
        missing.append("order_action_endpoint")
    if missing:
        raise ValueError(
            "missing verified chatbot bridge seams for planning: " + ", ".join(sorted(missing))
        )

    auth_contract = _infer_bridge_auth_contract(
        source_root=source_root,
        backend_framework=backend_framework,
        site_id=site_id,
        auth_handler_source=auth_handler_source,
        auth_style_hint=auth_style_hint,
    )
    response_contract = _infer_bridge_response_contract(
        source_root=source_root,
        domain_integration=domain_integration,
        site_id=site_id,
        order_lookup_target=order_lookup_target,
    )
    order_action_contract = _infer_bridge_order_action_contract(
        domain_integration=domain_integration,
        response_contract=response_contract,
    )

    return {
        "auth_validation_endpoint": auth_validation_endpoint,
        "current_user_endpoint": current_user_endpoint,
        "product_search_endpoint": product_search_endpoint,
        "order_list_endpoint": order_list_endpoint,
        "order_detail_endpoint": order_detail_endpoint,
        "order_action_endpoint": order_action_endpoint
        or next(iter(order_action_endpoints.values())),
        "order_action_endpoints": order_action_endpoints,
        "auth_contract": auth_contract,
        "response_contract": response_contract,
        "order_action_contract": order_action_contract,
        "response_mapping_profile": response_contract.order_profile,
        "request_field_mappings": order_action_contract.request_fields.model_dump(mode="json"),
    }


def _infer_bridge_response_contract(
    *,
    source_root: Path,
    domain_integration: DomainIntegration,
    site_id: str,
    order_lookup_target: str | None = None,
) -> ResolvedResponseContract:
    order_list_endpoint = str(domain_integration.order_list_endpoint or "").strip()
    order_detail_endpoint = str(domain_integration.order_detail_endpoint or "").strip()
    lookup_source = _read_bridge_source(
        source_root=source_root,
        relative_path=order_lookup_target,
    )
    if (
        "{user_id}" in order_list_endpoint
        or "{user_id}" in order_detail_endpoint
        or "get_order_by_number" in lookup_source
        or "order_number" in lookup_source
    ):
        return ResolvedResponseContract(
            user_profile="direct_user_session",
            product_profile="catalog_items_keyword_results",
            order_profile="user_scoped_order_service",
            delivery_profile="shipping_tracking_record",
            order_status_profile="service_tokens",
            delivery_status_profile="service_tokens",
            order_identifier_mode="order_number_with_internal_resolution",
        )
    if (
        order_list_endpoint.endswith("/all")
        or order_detail_endpoint == order_list_endpoint
        or "orders = raw.get(\"orders\"" in lookup_source
        or "orders = raw.get('orders'" in lookup_source
    ):
        return ResolvedResponseContract(
            user_profile="orders_collection_user_id",
            product_profile="products_wrapper_collection",
            order_profile="orders_collection_scan",
            delivery_profile="orders_collection_scan",
            order_status_profile="korean_labels",
            delivery_status_profile="korean_labels",
            order_identifier_mode="direct_order_id",
        )
    return ResolvedResponseContract(
        user_profile="wrapped_user",
        product_profile="list_items_named_price",
        order_profile="rest_detail_wrapped_order",
        delivery_profile="rest_detail_wrapped_order",
        order_status_profile="english_tokens",
        delivery_status_profile="english_tokens",
        order_identifier_mode="direct_order_id",
    )


def _infer_bridge_order_action_contract(
    *,
    domain_integration: DomainIntegration,
    response_contract: ResolvedResponseContract,
) -> ResolvedOrderActionContract:
    request_fields = ResolvedRequestFieldContract()
    if response_contract.order_profile == "orders_collection_scan":
        return ResolvedOrderActionContract(
            submission_mode="read_only",
            supported_actions=["list_orders", "get_order_status"],
            request_fields=request_fields,
        )

    order_action_endpoints = {
        str(action).strip(): str(path).strip()
        for action, path in (domain_integration.order_action_endpoints or {}).items()
        if str(action).strip() and str(path).strip()
    }
    if order_action_endpoints and any(
        path != str(domain_integration.order_action_endpoint or "").strip()
        for path in order_action_endpoints.values()
    ):
        mutation_actions = [
            action
            for action in ("cancel", "refund", "exchange")
            if action in order_action_endpoints
        ]
        return ResolvedOrderActionContract(
            submission_mode="per_action_query_endpoint",
            supported_actions=["list_orders", "get_order_status", *mutation_actions],
            request_fields=request_fields,
            reason_transport="query_param",
            new_option_transport=(
                "query_param" if "exchange" in mutation_actions else "unsupported"
            ),
            result_profile="requested_message",
        )

    return ResolvedOrderActionContract(
        submission_mode="single_endpoint_json_body",
        supported_actions=list(SUPPORTED_ORDER_TOOLS),
        request_fields=request_fields,
        reason_transport="json_body",
        new_option_transport="json_body",
        result_profile="accepted_message",
    )


def _read_bridge_source(*, source_root: Path, relative_path: str | None) -> str:
    candidate = str(relative_path or "").strip()
    if not candidate:
        return ""
    path = source_root / candidate
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _infer_bridge_auth_contract(
    *,
    source_root: Path,
    backend_framework: str,
    site_id: str,
    auth_handler_source: str,
    auth_style_hint: str,
) -> ResolvedAuthContract:
    candidate_paths = _auth_transport_candidate_paths(
        source_root=source_root,
        auth_handler_source=auth_handler_source,
    )
    evidence = _collect_auth_transport_evidence(candidate_paths)

    if evidence["supports_bearer"]:
        return ResolvedAuthContract(transport="bearer_token")

    session_cookie_name = evidence["session_cookie_name"]
    csrf_cookie_name = evidence["csrf_cookie_name"]
    csrf_header_name = evidence["csrf_header_name"]

    if session_cookie_name and csrf_cookie_name and csrf_header_name and evidence["has_csrf_evidence"]:
        return ResolvedAuthContract(
            transport="cookie_plus_csrf",
            session_cookie_name=session_cookie_name,
            csrf_cookie_name=csrf_cookie_name,
            csrf_header_name=csrf_header_name,
        )

    if session_cookie_name and evidence["has_cookie_evidence"]:
        return ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name=session_cookie_name,
        )

    normalized_hint = str(auth_style_hint or "").strip().lower()
    normalized_site = _normalize_site_key(site_id)
    if normalized_site == "bilyeo" or normalized_hint in {"bearer", "bearer_token"}:
        return ResolvedAuthContract(transport="bearer_token")
    if normalized_hint == "cookie_plus_csrf":
        return ResolvedAuthContract(
            transport="cookie_plus_csrf",
            session_cookie_name=session_cookie_name or "session_token",
            csrf_cookie_name=csrf_cookie_name or "csrftoken",
            csrf_header_name=csrf_header_name or "X-CSRFToken",
        )
    return ResolvedAuthContract(
        transport="session_cookie",
        session_cookie_name=session_cookie_name or "session_token",
    )


def _auth_transport_candidate_paths(
    *,
    source_root: Path,
    auth_handler_source: str,
) -> list[Path]:
    candidate_paths: list[Path] = []
    for relative_path in (
        str(auth_handler_source or "").strip(),
        "backend/chat_auth.py",
    ):
        if not relative_path:
            continue
        candidate = source_root / relative_path
        if candidate.exists() and candidate not in candidate_paths:
            candidate_paths.append(candidate)
    candidate_paths.extend(
        path
        for path in sorted(source_root.rglob("chat_auth.py"))
        if path not in candidate_paths
    )
    return candidate_paths


def _collect_auth_transport_evidence(candidate_paths: list[Path]) -> dict[str, Any]:
    supports_bearer = False
    session_cookie_name: str | None = None
    csrf_cookie_name: str | None = None
    csrf_header_name: str | None = None
    has_cookie_evidence = False
    has_csrf_evidence = False

    for candidate in candidate_paths:
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        lowered = content.lower()
        assignments = _extract_auth_constant_assignments(content)
        if _flask_chat_auth_supports_bearer_transport(content):
            supports_bearer = True
        if "request.cookies.get" in lowered or "set_cookie(" in lowered:
            has_cookie_evidence = True
        if "csrf" in lowered:
            has_csrf_evidence = True
        extracted_session_cookie = _extract_session_cookie_name(content, assignments)
        extracted_csrf_cookie = _extract_csrf_cookie_name(content, assignments)
        extracted_csrf_header = _extract_csrf_header_name(content, assignments)
        if session_cookie_name is None and extracted_session_cookie:
            session_cookie_name = extracted_session_cookie
        if csrf_cookie_name is None and extracted_csrf_cookie:
            csrf_cookie_name = extracted_csrf_cookie
        if csrf_header_name is None and extracted_csrf_header:
            csrf_header_name = extracted_csrf_header

    return {
        "supports_bearer": supports_bearer,
        "session_cookie_name": session_cookie_name,
        "csrf_cookie_name": csrf_cookie_name,
        "csrf_header_name": csrf_header_name,
        "has_cookie_evidence": has_cookie_evidence,
        "has_csrf_evidence": has_csrf_evidence,
    }


def _extract_auth_constant_assignments(content: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for match in re.finditer(
        r'(?m)^(?P<name>[A-Z][A-Z0-9_]+)\s*=\s*["\'](?P<value>[^"\']+)["\']',
        content,
    ):
        assignments[str(match.group("name")).strip()] = str(match.group("value")).strip()
    return assignments


def _extract_session_cookie_name(content: str, assignments: dict[str, str]) -> str | None:
    for key in ("SESSION_TOKEN_COOKIE_NAME", "SESSION_COOKIE_NAME"):
        value = assignments.get(key)
        if value:
            return value
    for value in _extract_cookie_candidates(content, assignments):
        if "csrf" not in value.lower():
            return value
    return None


def _extract_csrf_cookie_name(content: str, assignments: dict[str, str]) -> str | None:
    value = assignments.get("CSRF_COOKIE_NAME")
    if value:
        return value
    for candidate in _extract_cookie_candidates(content, assignments):
        if "csrf" in candidate.lower():
            return candidate
    return None


def _extract_csrf_header_name(content: str, assignments: dict[str, str]) -> str | None:
    value = assignments.get("CSRF_HEADER_NAME")
    if value:
        return value
    for match in re.finditer(
        r'request\.(?:headers|META)\.get\((?P<token>[^)]+)\)',
        content,
    ):
        resolved = _resolve_assignment_or_literal(match.group("token"), assignments)
        if not resolved:
            continue
        if resolved.startswith("HTTP_"):
            resolved = _http_meta_name_to_header(resolved)
        if "csrf" in resolved.lower():
            return resolved
    return None


def _extract_cookie_candidates(content: str, assignments: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r'request\.COOKIES\.get\((?P<token>[^)]+)\)',
        r'request\.cookies\.get\((?P<token>[^)]+)\)',
        r'set_cookie\((?P<token>[^,\n]+)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            resolved = _resolve_assignment_or_literal(match.group("token"), assignments)
            if resolved and resolved not in candidates:
                candidates.append(resolved)
    return candidates


def _resolve_assignment_or_literal(token: str, assignments: dict[str, str]) -> str | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    if raw.endswith(","):
        raw = raw[:-1].strip()
    if raw[:1] in {'"', "'"} and raw[-1:] == raw[:1]:
        return raw[1:-1].strip() or None
    return assignments.get(raw)


def _http_meta_name_to_header(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("HTTP_"):
        return normalized
    suffix = normalized[len("HTTP_") :]
    if suffix.upper() == "X_CSRFTOKEN":
        return "X-CSRFToken"
    return "-".join(part.title() for part in suffix.split("_") if part)


def _flask_chat_auth_supports_bearer_transport(content: str) -> bool:
    lowered = str(content or "").lower()
    has_bearer_markers = (
        "_parse_bearer_token" in content
        or ("authorization" in lowered and "bearer" in lowered)
    )
    resolves_authenticated_user = "resolve_authenticated_user_id" in content
    return has_bearer_markers and resolves_authenticated_user


def _derive_host_login_endpoint(domain_integration: DomainIntegration) -> str:
    login_endpoint = str(domain_integration.login_endpoint or "").strip()
    if login_endpoint:
        return login_endpoint
    raise ValueError("missing verified host login endpoint for planning")


def _resolve_site_id(snapshot: AnalysisSnapshot) -> str:
    site_id = str(snapshot.repo_profile.site or "").strip()
    if site_id:
        return site_id
    raise ValueError("analysis snapshot must provide a non-empty site id for planning")
