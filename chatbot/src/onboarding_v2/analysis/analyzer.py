from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

from chatbot.src.onboarding.onboarding_ignore import OnboardingIgnoreMatcher
from chatbot.src.onboarding_v2.llm_runtime import invoke_structured_stage
from chatbot.src.onboarding_v2.models.analysis import (
    AmbiguitySnapshot,
    AnalysisBundle,
    AnalysisGraph,
    AnalysisGraphEdge,
    AnalysisGraphNode,
    AnalysisProvenance,
    AnalysisSnapshot,
    BackendSeams,
    CandidateSet,
    ContractRecord,
    DomainIntegration,
    EvidencePacket,
    FrameworkProfile,
    FrontendSeams,
    ReadTarget,
    RagSourceRecord,
    RagSources,
    RejectedClaim,
    RetrievalPlan,
    RepoProfile,
    SearchIntent,
    VerifiedContracts,
    WorkspaceProfile,
)
from chatbot.src.onboarding_v2.models.common import ArtifactRef, PathCandidate
from chatbot.src.onboarding_v2.storage import DebugStore, LlmUsageStore

_RETRIEVAL_PLAN_PROMPT = """You are the analyze retrieval planner for onboarding_v2.
Return JSON matching the RetrievalPlan schema with keys:
- search_intents: array of objects with label, query, rationale, owner
- read_targets: array of file paths

Rules:
- Prefer route/auth/order/model/api-client targets.
- Never invent files that are not present in the candidate input.
- Owners should be "llm" when semantic judgment is needed and "deterministic" otherwise.
- Do not include markdown."""

_READ_QUEUE_PROMPT = """You are the analyze evidence reader planner for onboarding_v2.
Return JSON with one key:
- read_queue: array of objects with path, kind, rationale, owner, priority, evidence_refs

Rules:
- Choose a small focused queue that can resolve DB/API/Auth/Tool contracts.
- Prefer backend route files before handlers, then models/schemas, then frontend api and app shell.
- Never invent paths.
- Do not include markdown."""

_EVIDENCE_PROMPT = """You are the analyze evidence summarizer for onboarding_v2.
Return JSON with one key:
- evidence_packets: array of objects with packet_id, kind, path, summary, owner, evidence_refs

Rules:
- Summaries must reflect only the provided file excerpts.
- Keep packet kinds stable with the input queue.
- Never invent symbols or files.
- Do not include markdown."""

_CONTRACT_PROMPT = """You are the analyze contract extractor for onboarding_v2.
Return JSON matching the VerifiedContracts schema with keys:
- database_entities
- api_endpoints
- auth_components
- tool_targets

Rules:
- Every contract must include identifier, kind, location, owner, details, evidence_refs.
- Use only provided evidence.
- Prefer canonical order/auth endpoints and concrete DB tables/models.
- Do not include markdown."""


class _ReadQueueEnvelope(BaseModel):
    read_queue: list[ReadTarget] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _EvidenceEnvelope(BaseModel):
    evidence_packets: list[EvidencePacket] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class _EndpointCatalogRecord(BaseModel):
    identifier: str
    path: str
    http_method: str | None = None
    source_path: str
    source_kind: str
    blueprint_symbol: str | None = None
    local_path: str | None = None

    model_config = ConfigDict(extra="forbid")


def build_analysis_bundle(
    *,
    site: str,
    source_root: str | Path,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini",
    llm_builder: Callable[[str, str, float], Any] | None = None,
    debug_store: DebugStore | None = None,
    usage_store: LlmUsageStore | None = None,
    attempt: int = 1,
    ambiguity_retry_limit: int = 1,
    overrides: dict[str, Any] | None = None,
    artifact_refs: list[ArtifactRef] | None = None,
) -> AnalysisBundle:
    root = _resolve_root(source_root)
    analysis_overrides = _normalize_analysis_overrides(overrides)
    workspace_profile = _build_workspace_profile(root=root)
    framework_profile = _build_framework_profile(root=root)

    retrieval_fallback = _build_retrieval_plan_fallback(
        workspace_profile=workspace_profile,
        framework_profile=framework_profile,
    )
    retrieval_plan = invoke_structured_stage(
        stage="analysis",
        phase="retrieval-plan",
        provider=llm_provider,
        model=llm_model,
        system_prompt=_RETRIEVAL_PLAN_PROMPT,
        payload={
            "site": site,
            "workspace_profile": workspace_profile.model_dump(mode="json"),
            "framework_profile": framework_profile.model_dump(mode="json"),
        },
        response_model=RetrievalPlan,
        fallback_payload=retrieval_fallback.model_dump(mode="json"),
        attempt=attempt,
        debug_store=debug_store,
        usage_store=usage_store,
        llm_builder=llm_builder,
        artifact_refs=artifact_refs,
    )

    candidate_set = _harvest_candidates(root=root, framework_profile=framework_profile)
    final_retrieval_plan = _merge_retrieval_plan_with_candidates(
        retrieval_plan=retrieval_plan,
        candidate_set=candidate_set,
    )

    verified_contracts = VerifiedContracts()
    rejected_claims: list[RejectedClaim] = []
    unresolved_ambiguities: list[str] = []
    evidence_packets: list[EvidencePacket] = []
    read_queue: list[ReadTarget] = []

    current_candidate_set = candidate_set
    current_retrieval_plan = final_retrieval_plan
    for retry_index in range(max(1, ambiguity_retry_limit + 1)):
        read_queue_fallback = _build_read_queue_fallback(current_candidate_set)
        read_queue_response = invoke_structured_stage(
            stage="analysis",
            phase=f"read-queue-r{retry_index}",
            provider=llm_provider,
            model=llm_model,
            system_prompt=_READ_QUEUE_PROMPT,
            payload={
                "site": site,
                "framework_profile": framework_profile.model_dump(mode="json"),
                "candidate_set": current_candidate_set.model_dump(mode="json"),
                "retrieval_plan": current_retrieval_plan.model_dump(mode="json"),
            },
            response_model=_ReadQueueEnvelope,
            fallback_payload={"read_queue": [item.model_dump(mode="json") for item in read_queue_fallback]},
            attempt=attempt,
            debug_store=debug_store,
            usage_store=usage_store,
            llm_builder=llm_builder,
            artifact_refs=artifact_refs,
        )
        read_queue = _sanitize_read_queue(
            read_queue=read_queue_response.read_queue,
            fallback=read_queue_fallback,
            root=root,
        )

        evidence_fallback = _build_evidence_packets(root=root, read_queue=read_queue)
        evidence_response = invoke_structured_stage(
            stage="analysis",
            phase=f"evidence-reading-r{retry_index}",
            provider=llm_provider,
            model=llm_model,
            system_prompt=_EVIDENCE_PROMPT,
            payload={
                "site": site,
                "read_queue": [item.model_dump(mode="json") for item in read_queue],
                "file_snippets": _collect_file_snippets(root=root, read_queue=read_queue),
            },
            response_model=_EvidenceEnvelope,
            fallback_payload={
                "evidence_packets": [packet.model_dump(mode="json") for packet in evidence_fallback]
            },
            attempt=attempt,
            debug_store=debug_store,
            usage_store=usage_store,
            llm_builder=llm_builder,
            artifact_refs=artifact_refs,
        )
        evidence_packets = _sanitize_evidence_packets(
            packets=evidence_response.evidence_packets,
            fallback=evidence_fallback,
            root=root,
        )

        extracted_fallback = _extract_contracts_fallback(
            root=root,
            framework_profile=framework_profile,
            candidate_set=current_candidate_set,
            evidence_packets=evidence_packets,
        )
        extracted_contracts = invoke_structured_stage(
            stage="analysis",
            phase=f"contract-extraction-r{retry_index}",
            provider=llm_provider,
            model=llm_model,
            system_prompt=_CONTRACT_PROMPT,
            payload={
                "site": site,
                "framework_profile": framework_profile.model_dump(mode="json"),
                "candidate_set": current_candidate_set.model_dump(mode="json"),
                "evidence_packets": [packet.model_dump(mode="json") for packet in evidence_packets],
            },
            response_model=VerifiedContracts,
            fallback_payload=extracted_fallback.model_dump(mode="json"),
            attempt=attempt,
            debug_store=debug_store,
            usage_store=usage_store,
            llm_builder=llm_builder,
            artifact_refs=artifact_refs,
        )
        extracted_contracts = _merge_extracted_contract_sets(
            primary=extracted_contracts,
            fallback=extracted_fallback,
        )
        extracted_contracts = _apply_analysis_contract_overrides(
            root=root,
            candidate_set=current_candidate_set,
            contracts=extracted_contracts,
            overrides=analysis_overrides,
        )

        verified_contracts, rejected_claims, unresolved_ambiguities = _verify_contracts(
            root=root,
            framework_profile=framework_profile,
            candidate_set=current_candidate_set,
            contracts=extracted_contracts,
            overrides=analysis_overrides,
        )
        if _analysis_coverage_satisfied(
            verified_contracts=verified_contracts,
            candidate_set=current_candidate_set,
        ):
            break
        if retry_index >= ambiguity_retry_limit:
            break
        current_retrieval_plan, current_candidate_set = _expand_for_missing_coverage(
            root=root,
            retrieval_plan=current_retrieval_plan,
            candidate_set=current_candidate_set,
            unresolved_ambiguities=unresolved_ambiguities,
            framework_profile=framework_profile,
        )

    analysis_graph = _build_analysis_graph(verified_contracts)
    rag_sources = _discover_rag_sources(
        root=root,
        framework_profile=framework_profile,
        candidate_set=current_candidate_set,
    )
    snapshot = _build_snapshot_from_bundle(
        site=site,
        root=root,
        workspace_profile=workspace_profile,
        framework_profile=framework_profile,
        candidate_set=current_candidate_set,
        verified_contracts=verified_contracts,
        unresolved_ambiguities=unresolved_ambiguities,
        rag_sources=rag_sources,
    )
    return AnalysisBundle(
        workspace_profile=workspace_profile,
        framework_profile=framework_profile,
        retrieval_plan=current_retrieval_plan,
        candidate_set=current_candidate_set,
        read_queue=read_queue,
        evidence_packets=evidence_packets,
        verified_contracts=verified_contracts,
        rejected_claims=rejected_claims,
        analysis_graph=analysis_graph,
        unresolved_ambiguities=unresolved_ambiguities,
        rag_sources=rag_sources,
        snapshot=snapshot,
    )


def build_analysis_snapshot(
    *,
    site: str,
    source_root: str | Path,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini",
    llm_builder: Callable[[str, str, float], Any] | None = None,
    debug_store: DebugStore | None = None,
    usage_store: LlmUsageStore | None = None,
    attempt: int = 1,
    overrides: dict[str, Any] | None = None,
) -> AnalysisSnapshot:
    return build_analysis_bundle(
        site=site,
        source_root=source_root,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_builder=llm_builder,
        debug_store=debug_store,
        usage_store=usage_store,
        attempt=attempt,
        overrides=overrides,
    ).snapshot


def _resolve_root(source_root: str | Path) -> Path:
    root = Path(source_root)
    if root.exists():
        return root
    candidate = Path.cwd() / root
    if candidate.exists():
        return candidate
    return root


def _build_workspace_profile(*, root: Path) -> WorkspaceProfile:
    backend_root = "backend" if (root / "backend").exists() else None
    frontend_root = "frontend" if (root / "frontend").exists() else None
    return WorkspaceProfile(
        root=str(root),
        backend_root=backend_root,
        frontend_root=frontend_root,
        manifest_path=None,
    )


def _build_framework_profile(*, root: Path) -> FrameworkProfile:
    backend_framework = _normalize_backend_framework(
        None,
        root=root,
    )
    frontend_framework = _normalize_frontend_framework(
        None,
        root=root,
    )
    auth_style = _normalize_auth_style(
        None,
        root=root,
    )
    orm_family = {
        "django": "django_orm",
        "fastapi": "sqlalchemy",
        "flask": "sqlalchemy_or_raw_sql",
    }.get(backend_framework, "unknown")
    return FrameworkProfile(
        backend_framework=backend_framework,
        frontend_framework=frontend_framework,
        auth_style=auth_style,
        orm_family=orm_family,
        confidence_notes=[
            "framework profile derived from deterministic repo fingerprinting",
        ],
    )


def _build_retrieval_plan_fallback(
    *,
    workspace_profile: WorkspaceProfile,
    framework_profile: FrameworkProfile,
) -> RetrievalPlan:
    backend_label = framework_profile.backend_framework
    frontend_label = framework_profile.frontend_framework
    search_intents = [
        SearchIntent(
            label="route_definitions",
            query=f"{backend_label} route definitions and registration",
            rationale="identify canonical API and auth entrypoints",
            owner="deterministic",
        ),
        SearchIntent(
            label="auth_bootstrap",
            query=f"{backend_label} auth flow and {frontend_label} auth state",
            rationale="locate host auth bridge inputs and frontend auth storage",
            owner="llm",
        ),
        SearchIntent(
            label="order_domain",
            query=f"{backend_label} order handlers, services, repositories, tables",
            rationale="connect chatbot order tools to backend execution paths",
            owner="llm",
        ),
        SearchIntent(
            label="db_models",
            query=f"{framework_profile.orm_family} models, tables, migrations",
            rationale="extract database schema and ownership",
            owner="deterministic",
        ),
        SearchIntent(
            label="frontend_mounts",
            query=f"{frontend_label} app shell, router boundary, widget mount",
            rationale="find the safest frontend insertion point",
            owner="llm",
        ),
        SearchIntent(
            label="api_clients",
            query=f"{frontend_label} API client and transport entrypoints",
            rationale="route chatbot transport through existing client code",
            owner="deterministic",
        ),
    ]
    read_targets = [
        target
        for target in (
            workspace_profile.manifest_path,
            "backend" if workspace_profile.backend_root else None,
            "frontend" if workspace_profile.frontend_root else None,
        )
        if target
    ]
    return RetrievalPlan(search_intents=search_intents, read_targets=read_targets)


def _merge_retrieval_plan_with_candidates(
    *,
    retrieval_plan: RetrievalPlan,
    candidate_set: CandidateSet,
) -> RetrievalPlan:
    fallback_targets = [
        *[item.path for item in candidate_set.route_definitions[:2]],
        *[item.path for item in candidate_set.auth_components[:2]],
        *[item.path for item in candidate_set.order_targets[:2]],
        *[item.path for item in candidate_set.models[:2]],
        *[item.path for item in candidate_set.api_clients[:1]],
        *[item.path for item in candidate_set.app_shells[:1]],
    ]
    merged_targets: list[str] = []
    for target in [*retrieval_plan.read_targets, *fallback_targets]:
        if target and target not in merged_targets:
            merged_targets.append(target)
    return retrieval_plan.model_copy(update={"read_targets": merged_targets})


def _harvest_candidates(*, root: Path, framework_profile: FrameworkProfile) -> CandidateSet:
    route_definitions: list[PathCandidate] = []
    auth_components: list[PathCandidate] = []
    models: list[PathCandidate] = []
    migrations: list[PathCandidate] = []
    api_clients: list[PathCandidate] = []
    app_shells: list[PathCandidate] = []
    router_boundaries: list[PathCandidate] = []
    widget_mounts: list[PathCandidate] = []
    order_targets: list[PathCandidate] = []
    serializers: list[PathCandidate] = []
    schemas: list[PathCandidate] = []
    services: list[PathCandidate] = []
    repositories: list[PathCandidate] = []

    for path, text in _iter_text_files(root):
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()

        if _is_route_definition(path=path, text=text):
            route_definitions.append(_candidate(relative, "route definition candidate"))
        if _is_auth_component(path=path, text=text):
            auth_components.append(_candidate(relative, "auth component candidate"))
        if _is_model_candidate(path=path, text=text):
            models.append(_candidate(relative, "database model candidate"))
        if "/migrations/" in lowered or lowered.endswith("alembic.ini"):
            migrations.append(_candidate(relative, "migration candidate"))
        if _is_api_client(path=path, text=text):
            api_clients.append(_candidate(relative, "frontend api client candidate"))
        if _is_app_shell(path=path, text=text):
            app_shells.append(_candidate(relative, "frontend app shell candidate"))
        if _is_router_boundary(path=path, text=text):
            router_boundaries.append(_candidate(relative, "frontend router boundary candidate"))
        if _is_widget_mount(path=path, text=text):
            widget_mounts.append(_candidate(relative, "frontend widget mount candidate"))
        if _is_order_target(path=path, text=text):
            order_targets.append(_candidate(relative, "order target candidate"))
        if lowered.endswith("serializers.py"):
            serializers.append(_candidate(relative, "serializer candidate"))
        if lowered.endswith("schemas.py"):
            schemas.append(_candidate(relative, "schema candidate"))
        if _is_service_candidate(relative):
            services.append(_candidate(relative, "service layer candidate"))
        if _is_repository_candidate(relative):
            repositories.append(_candidate(relative, "repository candidate"))

    if framework_profile.backend_framework == "django":
        route_definitions = _promote_candidates(
            route_definitions,
            preferred_suffixes=["backend/foodshop/urls.py", "backend/config/urls.py", "backend/project/urls.py"],
        )
    elif framework_profile.backend_framework == "flask":
        route_definitions = _promote_candidates(route_definitions, preferred_suffixes=["backend/app.py"])
    elif framework_profile.backend_framework == "fastapi":
        route_definitions = _promote_candidates(route_definitions, preferred_suffixes=["backend/app/main.py"])

    app_shells = _promote_candidates(
        app_shells,
        preferred_suffixes=[
            "frontend/src/app.js",
            "frontend/src/app.jsx",
            "frontend/src/app.vue",
            "frontend/app/layout.tsx",
            "frontend/app/page.tsx",
        ],
    )
    api_clients = _promote_candidates(
        api_clients,
        preferred_suffixes=["frontend/src/api/api.js", "frontend/src/api/index.js", "frontend/app/order/page.tsx"],
    )
    order_targets = _promote_candidates(
        order_targets,
        preferred_suffixes=[
            "backend/orders/views.py",
            "backend/routes/order.py",
            "backend/app/router/orders/router.py",
            "backend/models/order.py",
        ],
    )
    return CandidateSet(
        route_definitions=_dedupe_candidates(route_definitions),
        auth_components=_dedupe_candidates(auth_components),
        models=_dedupe_candidates(models),
        migrations=_dedupe_candidates(migrations),
        api_clients=_dedupe_candidates(api_clients),
        app_shells=_dedupe_candidates(app_shells),
        router_boundaries=_dedupe_candidates(router_boundaries),
        widget_mounts=_dedupe_candidates(widget_mounts),
        order_targets=_dedupe_candidates(order_targets),
        serializers=_dedupe_candidates(serializers),
        schemas=_dedupe_candidates(schemas),
        services=_dedupe_candidates(services),
        repositories=_dedupe_candidates(repositories),
    )


def _build_read_queue_fallback(candidate_set: CandidateSet) -> list[ReadTarget]:
    queued: list[ReadTarget] = []
    for kind, candidates, rationale in [
        ("route_definition", candidate_set.route_definitions[:2], "resolve backend route topology first"),
        ("auth_component", candidate_set.auth_components[:2], "trace auth bootstrap and session resolution"),
        ("order_target", candidate_set.order_targets[:2], "trace order lookup and action execution"),
        ("database_model", candidate_set.models[:2], "resolve tables and schema ownership"),
        ("schema", candidate_set.schemas[:1], "attach request and response contracts"),
        ("serializer", candidate_set.serializers[:1], "attach request and response contracts"),
        ("api_client", candidate_set.api_clients[:1], "verify frontend transport binding"),
        ("app_shell", candidate_set.app_shells[:1], "verify widget mount boundary"),
    ]:
        for priority, candidate in enumerate(candidates, start=len(queued) + 1):
            queued.append(
                ReadTarget(
                    path=candidate.path,
                    kind=kind,
                    rationale=rationale,
                    owner="deterministic",
                    priority=priority,
                    evidence_refs=list(candidate.evidence_refs or [candidate.path]),
                )
            )
    return queued


def _sanitize_read_queue(
    *,
    read_queue: list[ReadTarget],
    fallback: list[ReadTarget],
    root: Path,
) -> list[ReadTarget]:
    sanitized: list[ReadTarget] = []
    seen: set[str] = set()
    for item in [*read_queue, *fallback]:
        if not item.path or item.path in seen or not (root / item.path).exists():
            continue
        seen.add(item.path)
        sanitized.append(item)
    return sanitized


def _build_evidence_packets(*, root: Path, read_queue: list[ReadTarget]) -> list[EvidencePacket]:
    packets: list[EvidencePacket] = []
    for item in read_queue:
        content = _read_excerpt(root / item.path)
        packets.append(
            EvidencePacket(
                packet_id=f"{item.kind}:{item.path}",
                kind=item.kind,
                path=item.path,
                summary=_summarize_excerpt(path=item.path, kind=item.kind, content=content),
                owner="deterministic",
                evidence_refs=[item.path],
            )
        )
    return packets


def _collect_file_snippets(*, root: Path, read_queue: list[ReadTarget]) -> list[dict[str, str]]:
    return [
        {
            "path": item.path,
            "kind": item.kind,
            "content": _read_excerpt(root / item.path),
        }
        for item in read_queue
    ]


def _normalize_analysis_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(overrides or {})
    normalized: dict[str, Any] = {}

    forced = []
    for item in raw.get("force_verify_endpoints") or []:
        if not isinstance(item, dict):
            continue
        path = _normalize_contract_endpoint_identifier(str(item.get("path") or ""))
        if not path:
            continue
        methods = _normalize_override_methods(item.get("methods"))
        handler_hint = str(item.get("handler_hint") or "").strip()
        forced.append(
            {
                "path": path,
                "methods": methods,
                "handler_hint": handler_hint,
            }
        )
    if forced:
        normalized["force_verify_endpoints"] = forced
    if "treat_api_view_as_method_source" in raw:
        normalized["treat_api_view_as_method_source"] = bool(raw.get("treat_api_view_as_method_source"))
    return normalized


def _normalize_override_methods(value: Any) -> list[str]:
    methods: list[str] = []
    for item in value or []:
        method = str(item or "").strip().upper()
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"} and method not in methods:
            methods.append(method)
    return methods


def _merge_extracted_contract_sets(
    *,
    primary: VerifiedContracts,
    fallback: VerifiedContracts,
) -> VerifiedContracts:
    return VerifiedContracts(
        database_entities=_dedupe_contracts([*primary.database_entities, *fallback.database_entities]),
        api_endpoints=_dedupe_contracts([*primary.api_endpoints, *fallback.api_endpoints]),
        auth_components=_dedupe_contracts([*primary.auth_components, *fallback.auth_components]),
        tool_targets=_dedupe_contracts([*primary.tool_targets, *fallback.tool_targets]),
    )


def _apply_analysis_contract_overrides(
    *,
    root: Path,
    candidate_set: CandidateSet,
    contracts: VerifiedContracts,
    overrides: dict[str, Any],
) -> VerifiedContracts:
    forced_records: list[ContractRecord] = []
    for item in overrides.get("force_verify_endpoints") or []:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        methods = _normalize_override_methods(item.get("methods"))
        handler_hint = str(item.get("handler_hint") or "").strip()
        handler_path = handler_hint.split(":", 1)[0].strip() if ":" in handler_hint else handler_hint
        location = handler_path or _find_endpoint_location(
            identifier=path,
            candidate_set=candidate_set,
            root=root,
        )
        details: dict[str, Any] = {"path": path}
        if methods:
            details["declared_http_methods"] = methods
        if len(methods) == 1:
            details["http_method"] = methods[0]
        if handler_hint:
            details["handler_hint"] = handler_hint
        forced_records.append(
            ContractRecord(
                identifier=path,
                kind="api_endpoint",
                location=location,
                owner="repair_override",
                details=details,
                evidence_refs=[ref for ref in [location, handler_path] if ref],
            )
        )
    if not forced_records:
        return contracts
    return contracts.model_copy(
        update={
            "api_endpoints": _dedupe_contracts([*contracts.api_endpoints, *forced_records]),
        }
    )


def _sanitize_evidence_packets(
    *,
    packets: list[EvidencePacket],
    fallback: list[EvidencePacket],
    root: Path,
) -> list[EvidencePacket]:
    sanitized: list[EvidencePacket] = []
    seen: set[tuple[str, str]] = set()
    for packet in [*packets, *fallback]:
        key = (packet.path, packet.kind)
        if not packet.path or key in seen or not (root / packet.path).exists():
            continue
        seen.add(key)
        sanitized.append(packet)
    return sanitized


def _extract_contracts_fallback(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
    evidence_packets: list[EvidencePacket],
) -> VerifiedContracts:
    del evidence_packets
    return VerifiedContracts(
        database_entities=_extract_database_entities(
            root=root,
            framework_profile=framework_profile,
            candidate_set=candidate_set,
        ),
        api_endpoints=_extract_api_endpoints(
            root=root,
            framework_profile=framework_profile,
            candidate_set=candidate_set,
        ),
        auth_components=_extract_auth_contracts(
            candidate_set=candidate_set,
            framework_profile=framework_profile,
        ),
        tool_targets=_extract_tool_targets(candidate_set=candidate_set),
    )


def _verify_contracts(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
    contracts: VerifiedContracts,
    overrides: dict[str, Any] | None = None,
) -> tuple[VerifiedContracts, list[RejectedClaim], list[str]]:
    analysis_overrides = _normalize_analysis_overrides(overrides)
    route_catalog = _build_route_catalog(
        root=root,
        framework_profile=framework_profile,
        candidate_set=candidate_set,
        prefer_decorator_methods=bool(analysis_overrides.get("treat_api_view_as_method_source")),
    )
    table_catalog = _build_table_catalog(
        root=root,
        framework_profile=framework_profile,
        candidate_set=candidate_set,
    )
    api_client_catalog = _build_api_client_catalog(root=root, candidate_set=candidate_set)
    route_by_path = {record.path: record for record in route_catalog}
    client_by_path = {record.path: record for record in api_client_catalog}
    route_aliases = _build_endpoint_alias_map(route_catalog)
    client_aliases = _build_endpoint_alias_map(api_client_catalog)

    verified = VerifiedContracts()
    rejected: list[RejectedClaim] = []
    ambiguities: list[str] = []

    for record in contracts.database_entities:
        canonical_record = _canonicalize_database_entity_contract(
            record=record,
            table_catalog=table_catalog,
        )
        text = _safe_read_text(root / record.location)
        if (root / record.location).exists() and (
            canonical_record.identifier in table_catalog
            or canonical_record.identifier in text
            or canonical_record.location.endswith("models.py")
        ):
            verified.database_entities.append(canonical_record)
        else:
            rejected.append(
                RejectedClaim(
                    identifier=canonical_record.identifier,
                    kind=canonical_record.kind,
                    reason="database entity could not be verified from models or table catalog",
                    evidence_refs=list(canonical_record.evidence_refs),
                )
            )

    for record in contracts.api_endpoints:
        canonical_record = _canonicalize_endpoint_input_contract(record)
        resolution = _resolve_endpoint_record(
            record=canonical_record,
            route_by_path=route_by_path,
            client_by_path=client_by_path,
            route_aliases=route_aliases,
            client_aliases=client_aliases,
            route_catalog=route_catalog,
        )
        if resolution is None:
            rejected.append(
                RejectedClaim(
                    identifier=canonical_record.identifier,
                    kind=canonical_record.kind,
                    reason="api endpoint could not be verified from route or client catalogs",
                    evidence_refs=list(canonical_record.evidence_refs),
                )
            )
            continue

        status, endpoint_record, mismatch_record = resolution
        if status == "server_route":
            verified.api_endpoints.append(
                _canonicalize_endpoint_contract(
                    record=canonical_record,
                    endpoint_record=endpoint_record,
                )
            )
            continue

        if status == "client_server_mismatch" and mismatch_record is not None:
            rejected.append(
                RejectedClaim(
                    identifier=endpoint_record.path,
                    kind=canonical_record.kind,
                    reason=(
                        f"client endpoint path {endpoint_record.path} does not match verified server route "
                        f"{mismatch_record.path}"
                    ),
                    evidence_refs=list(
                        dict.fromkeys(
                            [
                                *canonical_record.evidence_refs,
                                endpoint_record.source_path,
                                mismatch_record.source_path,
                            ]
                        )
                    ),
                )
            )
            continue

        rejected.append(
            RejectedClaim(
                identifier=endpoint_record.path,
                kind=canonical_record.kind,
                reason="api endpoint appears only in frontend client catalog and could not be verified from server routes",
                evidence_refs=list(dict.fromkeys([*canonical_record.evidence_refs, endpoint_record.source_path])),
            )
        )

    for record in contracts.auth_components:
        content = _safe_read_text(root / record.location)
        if (root / record.location).exists() and _looks_like_auth_content(content):
            verified.auth_components.extend(
                _canonicalize_auth_component_contracts(
                    record=record,
                    content=content,
                )
            )
        else:
            rejected.append(
                RejectedClaim(
                    identifier=record.identifier,
                    kind=record.kind,
                    reason="auth component file missing or lacking auth markers",
                    evidence_refs=list(record.evidence_refs),
                )
            )

    for record in contracts.tool_targets:
        content = _safe_read_text(root / record.location)
        if (root / record.location).exists() and "order" in content.lower():
            canonicalized = _canonicalize_tool_target_contracts(
                record=record,
                content=content,
            )
            if canonicalized:
                verified.tool_targets.extend(canonicalized)
            elif record.identifier in {"order_lookup", "order_action"}:
                verified.tool_targets.append(record)
            else:
                rejected.append(
                    RejectedClaim(
                        identifier=record.identifier,
                        kind=record.kind,
                        reason="tool target could not be mapped to planner-critical order_lookup/order_action contracts",
                        evidence_refs=list(record.evidence_refs),
                    )
                )
        else:
            rejected.append(
                RejectedClaim(
                    identifier=record.identifier,
                    kind=record.kind,
                    reason="tool target file missing or not order-related",
                    evidence_refs=list(record.evidence_refs),
                )
            )

    if len(candidate_set.app_shells) > 1:
        ambiguities.append("multiple frontend app shell candidates detected")
    if len(candidate_set.router_boundaries) > 1:
        ambiguities.append("multiple router boundary candidates detected")
    if not verified.database_entities:
        ambiguities.append("verified database entities missing")
    if not any("order" in record.identifier.lower() for record in verified.api_endpoints):
        ambiguities.append("verified order api endpoint missing")
    if not any(record.identifier == "chat_auth_bootstrap" for record in verified.auth_components):
        ambiguities.append("verified auth bootstrap contract missing")
    if not any(record.identifier == "order_lookup" for record in verified.tool_targets):
        ambiguities.append("verified order lookup target missing")
    if not any(record.identifier == "order_action" for record in verified.tool_targets):
        ambiguities.append("verified order action target missing")

    return (
        VerifiedContracts(
            database_entities=_dedupe_contracts(verified.database_entities),
            api_endpoints=_dedupe_contracts(verified.api_endpoints),
            auth_components=_dedupe_contracts(verified.auth_components),
            tool_targets=_dedupe_contracts(verified.tool_targets),
        ),
        rejected,
        list(dict.fromkeys(ambiguities)),
    )


def _analysis_coverage_satisfied(
    *,
    verified_contracts: VerifiedContracts,
    candidate_set: CandidateSet,
) -> bool:
    return (
        bool(verified_contracts.database_entities)
        and any("order" in record.identifier.lower() for record in verified_contracts.api_endpoints)
        and any(record.identifier == "chat_auth_bootstrap" for record in verified_contracts.auth_components)
        and any(record.identifier == "order_lookup" for record in verified_contracts.tool_targets)
        and any(record.identifier == "order_action" for record in verified_contracts.tool_targets)
        and bool(candidate_set.api_clients)
        and bool(candidate_set.app_shells)
    )


def _expand_for_missing_coverage(
    *,
    root: Path,
    retrieval_plan: RetrievalPlan,
    candidate_set: CandidateSet,
    unresolved_ambiguities: list[str],
    framework_profile: FrameworkProfile,
) -> tuple[RetrievalPlan, CandidateSet]:
    extra_intents = list(retrieval_plan.search_intents)
    for question in unresolved_ambiguities:
        if question == "verified database entities missing":
            extra_intents.append(
                SearchIntent(
                    label="followup_db",
                    query=f"{framework_profile.orm_family} order tables and migrations",
                    rationale="database coverage was incomplete on the previous analysis pass",
                    owner="llm",
                )
            )
        if question == "verified auth bootstrap contract missing":
            extra_intents.append(
                SearchIntent(
                    label="followup_auth",
                    query=f"{framework_profile.backend_framework} auth bootstrap and login endpoints",
                    rationale="auth coverage was incomplete on the previous analysis pass",
                    owner="llm",
                )
            )
    refreshed_candidates = _harvest_candidates(root=root, framework_profile=framework_profile)
    return (
        retrieval_plan.model_copy(
            update={
                "search_intents": extra_intents,
                "read_targets": _merge_retrieval_plan_with_candidates(
                    retrieval_plan=retrieval_plan,
                    candidate_set=refreshed_candidates,
                ).read_targets,
            }
        ),
        refreshed_candidates.model_copy(
            update={
                "app_shells": _dedupe_candidates([*candidate_set.app_shells, *refreshed_candidates.app_shells]),
                "router_boundaries": _dedupe_candidates(
                    [*candidate_set.router_boundaries, *refreshed_candidates.router_boundaries]
                ),
            }
        ),
    )


def _build_snapshot_from_bundle(
    *,
    site: str,
    root: Path,
    workspace_profile: WorkspaceProfile,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
    verified_contracts: VerifiedContracts,
    unresolved_ambiguities: list[str],
    rag_sources: RagSources,
) -> AnalysisSnapshot:
    backend_entrypoints = [item.path for item in candidate_set.route_definitions[:3]]
    frontend_entrypoints = [item.path for item in candidate_set.app_shells[:3]]
    auth_sources = _promote_candidates([
        item
        for item in candidate_set.auth_components
        if item.path.startswith("backend/")
    ],
        preferred_suffixes=[
            "backend/users/views.py",
            "backend/routes/auth.py",
            "backend/app/core/auth.py",
            "backend/app/router/users/router.py",
        ],
    )
    frontend_auth = _promote_candidates([
        item
        for item in candidate_set.auth_components
        if item.path.startswith("frontend/")
    ],
        preferred_suffixes=[
            "frontend/src/context/AuthContext.jsx",
            "frontend/src/api/api.js",
            "frontend/src/api/index.js",
            "frontend/app/authcontext.tsx",
        ],
    )
    order_api_paths = [
        record.identifier
        for record in verified_contracts.api_endpoints
        if "order" in record.identifier.lower()
    ]
    product_api_paths = [
        record.identifier
        for record in verified_contracts.api_endpoints
        if "product" in record.identifier.lower()
    ]
    order_targets = [
        PathCandidate(
            path=record.location,
            reason="verified order tool target",
            source=record.owner,
            evidence_refs=list(record.evidence_refs),
        )
        for record in verified_contracts.tool_targets
    ]
    endpoint_index = {
        str(record.identifier or "").strip(): str(record.details.get("path") or record.identifier or "").strip()
        for record in verified_contracts.api_endpoints
        if str(record.identifier or "").strip()
    }
    login_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/users/login/", "/api/auth/login", "/api/session/login", "/api/login"],
        fallbacks=["/api/users/login/", "/api/auth/login"],
    )
    auth_validation_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/users/me/", "/api/auth/me", "/api/session/me"],
        fallbacks=["/api/auth/login", "/api/users/login/"],
    )
    current_user_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/users/me/", "/api/auth/me", "/api/session/me"],
        fallbacks=[auth_validation_endpoint],
    )
    product_search_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/products/", "/api/products"],
        fallbacks=["/api/products/{product_id}", "/api/products/categories"],
    )
    order_list_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/orders/", "/api/orders/all", "/api/orders"],
        fallbacks=[],
    )
    order_detail_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/orders/{order_id}/", "/api/orders/{order_id}"],
        fallbacks=[],
    )
    order_action_endpoint = _resolve_endpoint_path(
        endpoint_index,
        preferred=["/api/orders/{order_id}/actions/"],
        fallbacks=["/api/orders/{order_id}/exchange", "/api/orders/{order_id}/refund", "/api/orders/{order_id}/cancel"],
    )
    order_action_endpoints = {
        action: path
        for action, path in {
            "cancel": endpoint_index.get("/api/orders/{order_id}/cancel", ""),
            "refund": endpoint_index.get("/api/orders/{order_id}/refund", ""),
            "exchange": endpoint_index.get("/api/orders/{order_id}/exchange", ""),
        }.items()
        if path
    }
    return AnalysisSnapshot(
        repo_profile=RepoProfile(
            site=site,
            source_root=str(root),
            backend_framework=framework_profile.backend_framework,
            frontend_framework=framework_profile.frontend_framework,
            auth_style=framework_profile.auth_style,
            backend_entrypoints=backend_entrypoints,
            frontend_entrypoints=frontend_entrypoints,
        ),
        backend_seams=BackendSeams(
            auth_source_candidates=auth_sources,
            user_resolver_candidates=[
                item
                for item in candidate_set.auth_components
                if item.path.startswith("backend/") and ("auth.py" in item.path or "users" in item.path)
            ],
            route_registration_points=candidate_set.route_definitions,
            tool_registry_candidates=candidate_set.services,
        ),
        frontend_seams=FrontendSeams(
            app_shell_candidates=candidate_set.app_shells,
            router_boundary_candidates=candidate_set.router_boundaries,
            api_client_candidates=candidate_set.api_clients,
            widget_mount_candidates=candidate_set.widget_mounts or candidate_set.app_shells,
            auth_store_candidates=frontend_auth,
        ),
        domain_integration=DomainIntegration(
            product_api_base_paths=product_api_paths,
            order_api_base_paths=order_api_paths,
            order_bridge_targets=order_targets or candidate_set.order_targets,
            login_endpoint=login_endpoint,
            auth_validation_endpoint=auth_validation_endpoint,
            current_user_endpoint=current_user_endpoint,
            product_search_endpoint=product_search_endpoint,
            order_list_endpoint=order_list_endpoint,
            order_detail_endpoint=order_detail_endpoint,
            order_action_endpoint=order_action_endpoint,
            order_action_endpoints=order_action_endpoints,
            site_id_source="cli_site_argument",
        ),
        rag_sources=rag_sources,
        ambiguity=AmbiguitySnapshot(
            open_questions=list(unresolved_ambiguities),
            competing_candidates=[],
            rejected_candidates=[
                PathCandidate(path=item.path, reason=item.reason, source=item.source)
                for item in candidate_set.router_boundaries[1:3]
            ],
        ),
        provenance=AnalysisProvenance(
            discovered_by=["deterministic", "llm_assisted"],
            llm_augmented=True,
            soft_dropped_candidates=[],
            evidence_refs=[
                *backend_entrypoints,
                *frontend_entrypoints,
            ],
            confidence_notes=list(dict.fromkeys([
                *framework_profile.confidence_notes,
                "snapshot derived from verified contracts and analysis graph",
            ])),
        ),
    )


def _discover_rag_sources(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
) -> RagSources:
    del framework_profile, candidate_set
    ignore_matcher = OnboardingIgnoreMatcher(root)
    faq_sources: list[RagSourceRecord] = []
    policy_sources: list[RagSourceRecord] = []
    discovery_image_sources: list[RagSourceRecord] = []
    allowed_suffixes = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt", ".md", ".csv"}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in allowed_suffixes:
            continue
        if not ignore_matcher.includes(path):
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        content_lower = content.lower()

        if _is_faq_source(lowered, content_lower):
            faq_sources.append(
                RagSourceRecord(
                    path=relative,
                    kind=_rag_source_kind(path),
                    corpus="faq",
                    reason="repo evidence suggests FAQ-style knowledge source",
                )
            )
        if _is_policy_source(lowered, content_lower):
            policy_sources.append(
                RagSourceRecord(
                    path=relative,
                    kind=_rag_source_kind(path),
                    corpus="policy",
                    reason="repo evidence suggests policy/terms knowledge source",
                )
            )
        if _is_discovery_image_source(lowered, content_lower):
            details = {}
            if "r2_" in content_lower or "cloudflare" in content_lower:
                details = {"loader_strategy": "remote_object_storage"}
            elif "image_url" in content_lower or "thumbnail" in content_lower:
                details = {"loader_strategy": "remote_image_url_fetch"}
            discovery_image_sources.append(
                RagSourceRecord(
                    path=relative,
                    kind=_rag_source_kind(path),
                    corpus="discovery_image",
                    reason="repo evidence suggests product image source",
                    details=details,
                )
            )

    return RagSources(
        faq=_dedupe_rag_source_records(faq_sources),
        policy=_dedupe_rag_source_records(policy_sources),
        discovery_image=_dedupe_rag_source_records(discovery_image_sources),
    )


def _rag_source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".md": "markdown_doc",
        ".txt": "text_doc",
        ".json": "json_file",
        ".csv": "csv_file",
        ".py": "crawl_script" if "script" in path.as_posix().lower() else "code_file",
        ".js": "code_file",
        ".jsx": "code_file",
        ".ts": "code_file",
        ".tsx": "code_file",
    }.get(suffix, "file")


def _dedupe_rag_source_records(items: list[RagSourceRecord]) -> list[RagSourceRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[RagSourceRecord] = []
    for item in items:
        key = (item.corpus, item.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _is_faq_source(path: str, content: str) -> bool:
    if "site-manifest.json" in path:
        return False
    return (
        "faq" in path
        or ("question" in content and "answer" in content)
        or ("faq" in content and "crawl" in content)
    )


def _is_policy_source(path: str, content: str) -> bool:
    if "site-manifest.json" in path:
        return False
    policy_tokens = ("policy", "terms", "refund", "return", "shipping", "exchange", "cancel", "약관", "환불", "반품", "교환", "배송")
    return any(token in path or token in content for token in policy_tokens)


def _is_discovery_image_source(path: str, content: str) -> bool:
    if "site-manifest.json" in path:
        return False
    image_tokens = ("image_url", "thumbnail", "image", "img", "cloudflare", "r2_bucket", "r2_", "s3", "media/")
    return any(token in path or token in content for token in image_tokens)


def _resolve_endpoint_path(
    endpoint_index: dict[str, str],
    *,
    preferred: list[str],
    fallbacks: list[str],
) -> str | None:
    for key in preferred:
        value = str(endpoint_index.get(key) or "").strip()
        if value:
            return value
    for key in fallbacks:
        value = str(endpoint_index.get(key) or "").strip()
        if value:
            return value
    return None


def _build_analysis_graph(verified_contracts: VerifiedContracts) -> AnalysisGraph:
    nodes: list[AnalysisGraphNode] = []
    edges: list[AnalysisGraphEdge] = []
    node_ids: set[str] = set()

    def add_node(prefix: str, record: ContractRecord) -> str:
        node_id = f"{prefix}:{record.identifier}"
        if node_id not in node_ids:
            node_ids.add(node_id)
            nodes.append(
                AnalysisGraphNode(
                    node_id=node_id,
                    kind=record.kind,
                    label=record.identifier,
                    path=record.location,
                    metadata=dict(record.details),
                    evidence_refs=list(record.evidence_refs),
                )
            )
        return node_id

    api_ids: list[str] = []
    db_ids: list[str] = []
    auth_ids: list[str] = []
    tool_ids: dict[str, str] = {}

    for record in verified_contracts.database_entities:
        db_ids.append(add_node("db", record))
    for record in verified_contracts.api_endpoints:
        api_ids.append(add_node("api", record))
    for record in verified_contracts.auth_components:
        auth_ids.append(add_node("auth", record))
    for record in verified_contracts.tool_targets:
        tool_ids[record.identifier] = add_node("tool", record)

    order_api_ids = [
        node_id
        for node_id in api_ids
        if "order" in node_id.lower()
    ]
    order_db_ids = [
        node_id
        for node_id in db_ids
        if "order" in node_id.lower()
    ]
    if order_api_ids and "order_lookup" in tool_ids:
        edges.append(
            AnalysisGraphEdge(
                source=order_api_ids[0],
                target=tool_ids["order_lookup"],
                relation="backs",
                evidence_refs=[order_api_ids[0]],
            )
        )
    if order_api_ids and "order_action" in tool_ids:
        edges.append(
            AnalysisGraphEdge(
                source=order_api_ids[0],
                target=tool_ids["order_action"],
                relation="backs",
                evidence_refs=[order_api_ids[0]],
            )
        )
    if order_db_ids and "order_lookup" in tool_ids:
        edges.append(
            AnalysisGraphEdge(
                source=tool_ids["order_lookup"],
                target=order_db_ids[0],
                relation="reads_from",
                evidence_refs=[order_db_ids[0]],
            )
        )
    if order_db_ids and "order_action" in tool_ids:
        edges.append(
            AnalysisGraphEdge(
                source=tool_ids["order_action"],
                target=order_db_ids[0],
                relation="writes_to",
                evidence_refs=[order_db_ids[0]],
            )
        )
    if "auth:chat_auth_bootstrap" in auth_ids:
        for auth_id in auth_ids:
            if auth_id != "auth:chat_auth_bootstrap":
                edges.append(
                    AnalysisGraphEdge(
                        source="auth:chat_auth_bootstrap",
                        target=auth_id,
                        relation="depends_on",
                        evidence_refs=["/api/chat/auth-token"],
                    )
                )
                break
    return AnalysisGraph(nodes=nodes, edges=edges)


def _extract_database_entities(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
) -> list[ContractRecord]:
    entities: list[ContractRecord] = []
    seen: set[tuple[str, str]] = set()
    if framework_profile.backend_framework == "django":
        class_pattern = re.compile(r"^class\s+(\w+)\s*\(models\.Model\):", re.MULTILINE)
        db_table_pattern = re.compile(r"^\s*db_table\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
        for candidate in candidate_set.models:
            if not candidate.path.endswith("models.py"):
                continue
            text = _safe_read_text(root / candidate.path)
            matches = list(class_pattern.finditer(text))
            for index, match in enumerate(matches):
                class_name = match.group(1)
                start = match.start()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                block = text[start:end]
                identifier = db_table_pattern.search(block)
                table_name = identifier.group(1) if identifier else class_name.lower()
                key = (table_name, candidate.path)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(
                    ContractRecord(
                        identifier=table_name,
                        kind="database_entity",
                        location=candidate.path,
                        owner="deterministic",
                        details={"model_name": class_name},
                        evidence_refs=[candidate.path],
                    )
                )
    elif framework_profile.backend_framework == "fastapi":
        class_pattern = re.compile(r"^class\s+(\w+)\s*\(", re.MULTILINE)
        table_pattern = re.compile(r"__tablename__\s*=\s*[\"']([^\"']+)[\"']")
        for candidate in candidate_set.models:
            text = _safe_read_text(root / candidate.path)
            if "__tablename__" not in text:
                continue
            class_match = class_pattern.search(text)
            table_match = table_pattern.search(text)
            if not table_match:
                continue
            table_name = table_match.group(1)
            class_name = class_match.group(1) if class_match else table_name.title()
            key = (table_name, candidate.path)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                ContractRecord(
                    identifier=table_name,
                    kind="database_entity",
                    location=candidate.path,
                    owner="deterministic",
                    details={"model_name": class_name},
                    evidence_refs=[candidate.path],
                )
            )
    else:
        create_table_pattern = re.compile(r"CREATE TABLE\s+([a-zA-Z0-9_]+)", re.IGNORECASE)
        for candidate in [*candidate_set.models, *candidate_set.order_targets]:
            text = _safe_read_text(root / candidate.path)
            for match in create_table_pattern.finditer(text):
                table_name = match.group(1)
                key = (table_name, candidate.path)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(
                    ContractRecord(
                        identifier=table_name,
                        kind="database_entity",
                        location=candidate.path,
                        owner="deterministic",
                        details={"source": "create_table"},
                        evidence_refs=[candidate.path],
                    )
                )
        sql_table_pattern = re.compile(
            r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-zA-Z0-9_]+)",
            re.IGNORECASE,
        )
        for candidate in candidate_set.order_targets:
            text = _safe_read_text(root / candidate.path)
            for match in sql_table_pattern.finditer(text):
                table_name = match.group(1)
                key = (table_name, candidate.path)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(
                    ContractRecord(
                        identifier=table_name,
                        kind="database_entity",
                        location=candidate.path,
                        owner="deterministic",
                        details={"source": "sql_query"},
                        evidence_refs=[candidate.path],
                    )
                )
    return _dedupe_contracts(entities)


def _extract_api_endpoints(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
) -> list[ContractRecord]:
    route_catalog = _build_route_catalog(root=root, framework_profile=framework_profile, candidate_set=candidate_set)
    api_client_catalog = _build_api_client_catalog(root=root, candidate_set=candidate_set)
    records: list[ContractRecord] = []
    for endpoint in _dedupe_endpoint_records([*route_catalog, *api_client_catalog]):
        domain = _infer_endpoint_domain(endpoint.path)
        records.append(
            ContractRecord(
                identifier=endpoint.path,
                kind="api_endpoint",
                location=endpoint.source_path,
                owner="deterministic",
                details={
                    "domain": domain,
                    "path": endpoint.path,
                    "http_method": endpoint.http_method,
                    "source_kind": endpoint.source_kind,
                },
                evidence_refs=[endpoint.source_path] if endpoint.source_path else [],
            )
        )
    bootstrap_source = _choose_backend_auth_source(candidate_set)
    if bootstrap_source:
        records.append(
            ContractRecord(
                identifier="/api/chat/auth-token",
                kind="api_endpoint",
                location=bootstrap_source,
                owner="deterministic",
                details={
                    "domain": "auth_bootstrap",
                    "path": "/api/chat/auth-token",
                    "http_method": "POST",
                    "source_kind": "server_route",
                },
                evidence_refs=[bootstrap_source],
            )
        )
    return _dedupe_contracts(records)


def _extract_auth_contracts(
    *,
    candidate_set: CandidateSet,
    framework_profile: FrameworkProfile,
) -> list[ContractRecord]:
    del framework_profile
    records: list[ContractRecord] = []
    backend_source = _choose_backend_auth_source(candidate_set)
    frontend_source = _choose_frontend_auth_source(candidate_set)
    if backend_source:
        records.append(
            ContractRecord(
                identifier="auth_handler",
                kind="auth_component",
                location=backend_source,
                owner="deterministic",
                details={"role": "backend_auth_source"},
                evidence_refs=[backend_source],
            )
        )
        records.append(
            ContractRecord(
                identifier="chat_auth_bootstrap",
                kind="auth_component",
                location=backend_source,
                owner="deterministic",
                details={"role": "chatbot_bootstrap_contract"},
                evidence_refs=[backend_source],
            )
        )
    if backend_source:
        records.append(
            ContractRecord(
                identifier="backend_session_resolver",
                kind="auth_component",
                location=backend_source,
                owner="deterministic",
                details={"role": "session_resolver"},
                evidence_refs=[backend_source],
            )
        )
    if frontend_source:
        records.append(
            ContractRecord(
                identifier="frontend_auth_store",
                kind="auth_component",
                location=frontend_source,
                owner="deterministic",
                details={"role": "frontend_auth_state"},
                evidence_refs=[frontend_source],
            )
        )
    return _dedupe_contracts(records)


def _extract_tool_targets(*, candidate_set: CandidateSet) -> list[ContractRecord]:
    lookup_target = _choose_tool_target(candidate_set.order_targets, role="lookup")
    action_target = _choose_tool_target(candidate_set.order_targets, role="action")
    records = []
    if lookup_target:
        records.append(
            ContractRecord(
                identifier="order_lookup",
                kind="tool_target",
                location=lookup_target,
                owner="deterministic",
                details={"tool_name": "list_orders"},
                evidence_refs=[lookup_target],
            )
        )
    if action_target:
        records.append(
            ContractRecord(
                identifier="order_action",
                kind="tool_target",
                location=action_target,
                owner="deterministic",
                details={"tool_name": "cancel|refund|exchange"},
                evidence_refs=[action_target],
            )
        )
    return records


def _build_route_catalog(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
    prefer_decorator_methods: bool = False,
) -> list[_EndpointCatalogRecord]:
    if framework_profile.backend_framework == "django":
        return _build_django_route_catalog(
            root=root,
            route_candidates=candidate_set.route_definitions,
            prefer_decorator_methods=prefer_decorator_methods,
        )
    if framework_profile.backend_framework == "flask":
        return _build_flask_route_catalog(root=root, route_candidates=candidate_set.route_definitions)
    if framework_profile.backend_framework == "fastapi":
        return _build_fastapi_route_catalog(root=root, route_candidates=candidate_set.route_definitions)
    return []


def _build_django_route_catalog(
    *,
    root: Path,
    route_candidates: list[PathCandidate],
    prefer_decorator_methods: bool = False,
) -> list[_EndpointCatalogRecord]:
    route_pattern = re.compile(r'path\(\s*[\'"]([^\'"]*)[\'"]\s*,\s*([A-Za-z0-9_\.]+)')
    include_pattern = re.compile(r'path\(\s*[\'"]([^\'"]*)[\'"].*include\(\s*[\'"]([^\'"]+)[\'"]\)')
    module_prefixes: dict[str, str] = {}
    file_patterns: dict[str, list[tuple[str, str | None]]] = {}
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        patterns = [(match.group(1), match.group(2)) for match in route_pattern.finditer(text)]
        file_patterns[candidate.path] = patterns
        for match in include_pattern.finditer(text):
            module_prefixes[match.group(2)] = _normalize_endpoint_template(match.group(1))

    endpoints: list[_EndpointCatalogRecord] = []
    for candidate in route_candidates:
        module_name = _django_module_name(candidate.path)
        prefix = module_prefixes.get(module_name)
        handler_methods = (
            _parse_django_view_methods(root / candidate.path)
            if prefer_decorator_methods
            else {}
        )
        for pattern, handler_ref in file_patterns.get(candidate.path, []):
            if pattern == "" and prefix:
                methods = _resolve_django_handler_methods(handler_ref=handler_ref, handler_methods=handler_methods)
                for method in methods or [None]:
                    endpoints.append(
                        _EndpointCatalogRecord(
                            identifier=prefix,
                            path=prefix,
                            http_method=method,
                            source_path=candidate.path,
                            source_kind="server_route",
                        )
                    )
                continue
            normalized = _normalize_endpoint_template(pattern)
            if prefix and candidate.path.endswith("/urls.py") and prefix != normalized:
                path = _join_url_parts(prefix, normalized)
            else:
                path = normalized
            if path:
                methods = _resolve_django_handler_methods(handler_ref=handler_ref, handler_methods=handler_methods)
                for method in methods or [None]:
                    endpoints.append(
                        _EndpointCatalogRecord(
                            identifier=path,
                            path=path,
                            http_method=method,
                            source_path=candidate.path,
                            source_kind="server_route",
                        )
                    )
    return _dedupe_endpoint_records(endpoints)


def _parse_django_view_methods(route_path: Path) -> dict[str, list[str]]:
    if route_path.name != "urls.py":
        return {}
    view_path = route_path.with_name("views.py")
    text = _safe_read_text(view_path)
    if not text:
        return {}

    methods_by_handler: dict[str, list[str]] = {}
    decorator_block_pattern = re.compile(
        r"(?P<decorators>(?:^[ \t]*@.*\n)+)^[ \t]*def[ \t]+(?P<name>\w+)\s*\(",
        re.MULTILINE,
    )
    for match in decorator_block_pattern.finditer(text):
        decorators = match.group("decorators") or ""
        methods: list[str] = []
        api_view_match = re.search(r"api_view\(\s*\[([^\]]+)\]\s*\)", decorators)
        require_methods_match = re.search(r"require_http_methods\(\s*\[([^\]]+)\]\s*\)", decorators)
        if api_view_match:
            methods = _parse_http_methods(api_view_match.group(1))
        elif require_methods_match:
            methods = _parse_http_methods(require_methods_match.group(1))
        elif "require_get" in decorators.lower():
            methods = ["GET"]
        elif "require_post" in decorators.lower():
            methods = ["POST"]
        if methods:
            methods_by_handler[match.group("name")] = methods
    return methods_by_handler


def _resolve_django_handler_methods(
    *,
    handler_ref: str | None,
    handler_methods: dict[str, list[str]],
) -> list[str]:
    if not handler_ref:
        return []
    return list(handler_methods.get(handler_ref.split(".")[-1], []))


def _build_flask_route_catalog(*, root: Path, route_candidates: list[PathCandidate]) -> list[_EndpointCatalogRecord]:
    register_pattern = re.compile(r"register_blueprint\(\s*([a-zA-Z0-9_]+),\s*url_prefix=['\"]([^'\"]+)['\"]")
    route_pattern = re.compile(
        r"@([a-zA-Z0-9_]+)\.route\(\s*['\"]([^'\"]+)['\"](?P<tail>.*?)\)",
        re.DOTALL,
    )
    methods_pattern = re.compile(r"methods\s*=\s*\[([^\]]+)\]")
    prefixes: dict[str, str] = {}
    endpoints: list[_EndpointCatalogRecord] = []
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        for match in register_pattern.finditer(text):
            prefixes[match.group(1)] = _normalize_endpoint_template(match.group(2))
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        for match in route_pattern.finditer(text):
            owner = match.group(1)
            local_path = _normalize_endpoint_template(match.group(2))
            prefix = prefixes.get(owner, "")
            external_path = local_path if owner == "app" else _join_url_parts(prefix, local_path)
            methods_match = methods_pattern.search(match.group("tail") or "")
            methods = _parse_http_methods(methods_match.group(1) if methods_match else "")
            for method in methods or [None]:
                if external_path:
                    endpoints.append(
                        _EndpointCatalogRecord(
                            identifier=external_path,
                            path=external_path,
                            http_method=method or "GET",
                            source_path=candidate.path,
                            source_kind="server_route",
                            blueprint_symbol=None if owner == "app" else owner,
                            local_path=local_path,
                        )
                    )
    return _dedupe_endpoint_records(endpoints)


def _build_fastapi_route_catalog(*, root: Path, route_candidates: list[PathCandidate]) -> list[_EndpointCatalogRecord]:
    import_pattern = re.compile(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+router\s+as\s+([a-zA-Z0-9_]+)")
    include_pattern = re.compile(r"include_router\(\s*([a-zA-Z0-9_]+),\s*prefix=['\"]([^'\"]+)['\"]")
    decorator_pattern = re.compile(r"@([a-zA-Z0-9_]+)\.(get|post|patch|put|delete)\(\s*['\"]([^'\"]+)['\"]")
    prefixes: dict[str, str] = {}
    alias_modules: dict[str, str] = {}
    endpoints: list[_EndpointCatalogRecord] = []
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        for match in import_pattern.finditer(text):
            alias_modules[match.group(2)] = match.group(1)
        for match in include_pattern.finditer(text):
            prefixes[match.group(1)] = _normalize_endpoint_template(match.group(2))
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        inferred_prefix = ""
        normalized_candidate = candidate.path.replace("\\", "/").removesuffix(".py")
        for alias, module_name in alias_modules.items():
            normalized_module = module_name.replace(".", "/")
            if normalized_module.endswith(normalized_candidate.replace("backend/", "")):
                inferred_prefix = prefixes.get(alias, "")
                break
            if any(token in normalized_candidate for token in normalized_module.split("/")):
                inferred_prefix = prefixes.get(alias, inferred_prefix)
        for match in decorator_pattern.finditer(text):
            router_name = match.group(1)
            method = (match.group(2) or "").upper()
            prefix = prefixes.get(router_name, inferred_prefix)
            path = _join_url_parts(prefix, match.group(3))
            if path:
                endpoints.append(
                    _EndpointCatalogRecord(
                        identifier=path,
                        path=path,
                        http_method=method,
                        source_path=candidate.path,
                        source_kind="server_route",
                    )
                )
    return _dedupe_endpoint_records(endpoints)


def _build_table_catalog(
    *,
    root: Path,
    framework_profile: FrameworkProfile,
    candidate_set: CandidateSet,
) -> list[str]:
    return [
        record.identifier
        for record in _extract_database_entities(
            root=root,
            framework_profile=framework_profile,
            candidate_set=candidate_set,
        )
    ]


def _build_api_client_catalog(*, root: Path, candidate_set: CandidateSet) -> list[_EndpointCatalogRecord]:
    base_url_pattern = re.compile(r"baseURL\s*:\s*['\"]([^'\"]+)['\"]")
    client_call_pattern = re.compile(r"\.((?:get|post|patch|put|delete))\(\s*['\"]([^'\"]+)['\"]")
    fetch_call_pattern = re.compile(r"fetch\(\s*['\"]([^'\"]+)['\"](?P<tail>.*?)\)", re.DOTALL)
    method_pattern = re.compile(r"method\s*:\s*['\"](GET|POST|PATCH|PUT|DELETE)['\"]", re.IGNORECASE)
    catalog: list[_EndpointCatalogRecord] = []
    for candidate in candidate_set.api_clients:
        text = _safe_read_text(root / candidate.path)
        base_url_match = base_url_pattern.search(text)
        base_url = _normalize_endpoint_template(base_url_match.group(1) if base_url_match else "")
        for match in client_call_pattern.finditer(text):
            path = _normalize_client_endpoint_path(base_url=base_url, path=match.group(2))
            if not path:
                continue
            catalog.append(
                _EndpointCatalogRecord(
                    identifier=path,
                    path=path,
                    http_method=(match.group(1) or "").upper(),
                    source_path=candidate.path,
                    source_kind="frontend_client",
                )
            )
        for match in fetch_call_pattern.finditer(text):
            path = _normalize_client_endpoint_path(base_url=base_url, path=match.group(1))
            if not path:
                continue
            method_match = method_pattern.search(match.group("tail") or "")
            catalog.append(
                _EndpointCatalogRecord(
                    identifier=path,
                    path=path,
                    http_method=(method_match.group(1).upper() if method_match else "GET"),
                    source_path=candidate.path,
                    source_kind="frontend_client",
                )
            )
    return _dedupe_endpoint_records(catalog)


def _find_endpoint_location(*, identifier: str, candidate_set: CandidateSet, root: Path) -> str:
    normalized = _normalize_endpoint_template(identifier)
    for candidate in [*candidate_set.route_definitions, *candidate_set.api_clients]:
        text = _safe_read_text(root / candidate.path)
        if normalized.rstrip("/") in text.replace('"', "'") or normalized in _build_api_client_catalog(root=root, candidate_set=CandidateSet(api_clients=[candidate])):
            return candidate.path
    return candidate_set.route_definitions[0].path if candidate_set.route_definitions else ""


def _choose_backend_auth_source(candidate_set: CandidateSet) -> str:
    preferred = [
        item.path
        for item in candidate_set.auth_components
        if item.path.startswith("backend/")
        and (
            item.path.endswith("users/views.py")
            or item.path.endswith("routes/auth.py")
            or item.path.endswith("core/auth.py")
            or item.path.endswith("router/users/router.py")
        )
    ]
    if preferred:
        return preferred[0]
    for item in candidate_set.auth_components:
        if item.path.startswith("backend/"):
            return item.path
    return ""


def _choose_frontend_auth_source(candidate_set: CandidateSet) -> str:
    preferred = [
        item.path
        for item in candidate_set.auth_components
        if item.path.startswith("frontend/")
        and ("auth" in item.path.lower() or "context" in item.path.lower())
    ]
    if preferred:
        return preferred[0]
    for item in candidate_set.auth_components:
        if item.path.startswith("frontend/"):
            return item.path
    return ""


def _choose_tool_target(candidates: list[PathCandidate], *, role: str) -> str:
    if not candidates:
        return ""
    enumerated = list(enumerate(candidates))
    ranked = sorted(
        enumerated,
        key=lambda item: (
            -_tool_role_score(item[1].path, role=role),
            item[0],
        ),
    )
    return ranked[0][1].path


def _tool_role_score(path: str, *, role: str) -> int:
    normalized = path.replace("\\", "/").lower()
    score = 0
    if role == "lookup":
        if any(token in normalized for token in ("lookup", "list", "detail", "views.py", "router.py", "order.py")):
            score += 4
    else:
        if any(token in normalized for token in ("action", "cancel", "refund", "exchange", "views.py", "router.py", "order.py")):
            score += 4
    if normalized.endswith(("/tests.py", "/urls.py")) or "/migrations/" in normalized:
        score -= 10
    if normalized.startswith("backend/"):
        score += 2
    return score


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "site-manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_backend_framework(value: Any, *, root: Path) -> str:
    normalized = str(value or "").strip().lower()
    if "django" in normalized or (root / "backend" / "manage.py").exists():
        return "django"
    if "fastapi" in normalized or (root / "backend" / "app" / "main.py").exists():
        return "fastapi"
    if "flask" in normalized or (root / "backend" / "app.py").exists():
        return "flask"
    return "unknown"


def _normalize_frontend_framework(value: Any, *, root: Path) -> str:
    normalized = str(value or "").strip().lower()
    if "next" in normalized or (root / "frontend" / "app").exists():
        return "next"
    if "vue" in normalized or any(path.suffix == ".vue" for path in (root / "frontend").rglob("*.vue")):
        return "vue"
    if "react" in normalized or (root / "frontend" / "src" / "App.js").exists():
        return "react"
    return "unknown"


def _normalize_auth_style(value: Any, *, root: Path) -> str:
    normalized = str(value or "").strip().lower()
    backend_session = False
    frontend_credentials = False
    bearer_markers = False
    for path, text in _iter_text_files(root):
        lowered = text.lower()
        relative = path.relative_to(root).as_posix().lower()
        if path.suffix == ".py" and (
            "from flask import session" in lowered
            or "session[" in lowered
            or "session.get(" in lowered
            or "session.clear(" in lowered
        ):
            backend_session = True
        if relative.startswith("frontend/") and (
            "withcredentials: true" in lowered
            or "credentials: \"include\"" in lowered
            or "credentials: 'include'" in lowered
        ):
            frontend_credentials = True
        if "authorization" in lowered and "bearer" in lowered:
            bearer_markers = True
    if backend_session and frontend_credentials:
        return "session_cookie"
    if bearer_markers:
        return "jwt_bearer"
    if normalized:
        return normalized
    return "unknown"


def _canonicalize_database_entity_contract(
    *,
    record: ContractRecord,
    table_catalog: list[str],
) -> ContractRecord:
    canonical_identifier = _canonicalize_database_identifier(record.identifier, table_catalog)
    if canonical_identifier == record.identifier:
        return record
    details = dict(record.details)
    details.setdefault("semantic_identifier", record.identifier)
    return record.model_copy(update={"identifier": canonical_identifier, "details": details})


def _canonicalize_database_identifier(identifier: str, table_catalog: list[str]) -> str:
    normalized = str(identifier or "").strip()
    if not normalized:
        return normalized
    catalog_by_lower = {item.lower(): item for item in table_catalog}
    if normalized.lower() in catalog_by_lower:
        return catalog_by_lower[normalized.lower()]
    tail = re.split(r"[./:]", normalized)[-1].strip().lower()
    return catalog_by_lower.get(tail, normalized)


def _canonicalize_endpoint_input_contract(record: ContractRecord) -> ContractRecord:
    identifier_methods = _extract_contract_endpoint_methods(record.identifier)
    canonical_identifier = _normalize_contract_endpoint_identifier(record.identifier)
    details = dict(record.details)
    raw_path = details.get("path")
    if raw_path:
        path_methods = _extract_contract_endpoint_methods(str(raw_path))
        details["path"] = _normalize_contract_endpoint_identifier(str(raw_path))
        if not identifier_methods:
            identifier_methods = path_methods
    if identifier_methods:
        details["declared_http_methods"] = list(identifier_methods)
        if len(identifier_methods) == 1:
            details["http_method"] = identifier_methods[0]
    if canonical_identifier == record.identifier and details == record.details:
        return record
    if canonical_identifier != record.identifier:
        details.setdefault("raw_identifier", record.identifier)
    return record.model_copy(update={"identifier": canonical_identifier, "details": details})


def _dedupe_endpoint_records(records: list[_EndpointCatalogRecord]) -> list[_EndpointCatalogRecord]:
    deduped: list[_EndpointCatalogRecord] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for record in records:
        key = (record.path, record.http_method, record.source_kind, record.source_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _parse_http_methods(raw: str) -> list[str]:
    methods = [
        item.strip().strip("'\"").upper()
        for item in str(raw or "").split(",")
        if item.strip().strip("'\"")
    ]
    return [method for method in methods if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}]


def _normalize_client_endpoint_path(*, base_url: str, path: str) -> str:
    normalized = _normalize_endpoint_template(path)
    if not normalized:
        return ""
    if base_url and not normalized.startswith(base_url.rstrip("/") + "/") and normalized != base_url:
        return _join_url_parts(base_url, normalized)
    return normalized


def _infer_endpoint_domain(path: str) -> str:
    lowered = str(path or "").lower()
    if "chat/auth-token" in lowered:
        return "auth_bootstrap"
    if "/orders" in lowered or "/order" in lowered:
        return "order"
    if "/products" in lowered or "/product" in lowered:
        return "product"
    if "/auth/" in lowered or lowered.endswith("/login") or lowered.endswith("/logout") or lowered.endswith("/me"):
        return "auth"
    return "generic"


def _build_endpoint_alias_map(records: list[_EndpointCatalogRecord]) -> dict[str, _EndpointCatalogRecord]:
    aliases: dict[str, _EndpointCatalogRecord] = {}
    for record in records:
        for alias in _endpoint_aliases(record):
            aliases.setdefault(alias, record)
    return aliases


def _endpoint_aliases(record: _EndpointCatalogRecord) -> set[str]:
    aliases = {
        str(record.identifier or "").strip().lower(),
        str(record.path or "").strip().lower(),
    }
    path = str(record.path or "").lower()
    method = str(record.http_method or "").upper()
    if _infer_endpoint_domain(path) == "order" and method == "GET":
        if path.endswith("/all"):
            aliases.update({"orders_all", "order_lookup"})
        elif "{order_id}" in path or "{id}" in path:
            aliases.update({"order_detail", "get_order"})
    if path.endswith("/login"):
        aliases.add("auth_login")
    if path.endswith("/logout"):
        aliases.add("auth_logout")
    if path.endswith("/me"):
        aliases.add("auth_me")
    if "chat/auth-token" in path:
        aliases.add("chat_auth_bootstrap")
    return {alias for alias in aliases if alias}


def _resolve_endpoint_record(
    *,
    record: ContractRecord,
    route_by_path: dict[str, _EndpointCatalogRecord],
    client_by_path: dict[str, _EndpointCatalogRecord],
    route_aliases: dict[str, _EndpointCatalogRecord],
    client_aliases: dict[str, _EndpointCatalogRecord],
    route_catalog: list[_EndpointCatalogRecord],
) -> tuple[str, _EndpointCatalogRecord, _EndpointCatalogRecord | None] | None:
    details_path = _normalize_endpoint_template(str((record.details or {}).get("path") or ""))
    identifier = str(record.identifier or "").strip()
    for candidate in [details_path, _normalize_endpoint_template(identifier)]:
        if not candidate:
            continue
        route_match = route_by_path.get(candidate)
        if route_match is not None:
            return ("server_route", route_match, None)
        client_match = client_by_path.get(candidate)
        if client_match is not None:
            mismatch = _find_nearest_server_route(client_match=client_match, route_catalog=route_catalog)
            if mismatch is not None and mismatch.path != client_match.path:
                return ("client_server_mismatch", client_match, mismatch)
            return ("frontend_client", client_match, mismatch)

    if _is_path_like_endpoint(identifier):
        return None

    semantic = identifier.lower()
    route_match = route_aliases.get(semantic)
    if route_match is not None:
        return ("server_route", route_match, None)
    client_match = client_aliases.get(semantic)
    if client_match is not None:
        mismatch = _find_nearest_server_route(client_match=client_match, route_catalog=route_catalog)
        if mismatch is not None and mismatch.path != client_match.path:
            return ("client_server_mismatch", client_match, mismatch)
        return ("frontend_client", client_match, mismatch)
    return None


def _find_nearest_server_route(
    *,
    client_match: _EndpointCatalogRecord,
    route_catalog: list[_EndpointCatalogRecord],
) -> _EndpointCatalogRecord | None:
    domain = _infer_endpoint_domain(client_match.path)
    method = str(client_match.http_method or "").upper()
    candidates = [
        record
        for record in route_catalog
        if _infer_endpoint_domain(record.path) == domain
        and (not method or str(record.http_method or "").upper() == method)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda record: (
            0 if record.path == client_match.path else 1,
            abs(len(record.path) - len(client_match.path)),
            record.path,
        ),
    )[0]


def _canonicalize_auth_component_contracts(
    *,
    record: ContractRecord,
    content: str,
) -> list[ContractRecord]:
    details = dict(record.details)
    semantic_identifier = str(record.identifier or "")
    lowered = " ".join(
        [
            semantic_identifier.lower(),
            record.location.lower(),
            json.dumps(details, ensure_ascii=False).lower(),
            content.lower(),
        ]
    )
    canonical_ids: list[str] = []
    if record.location.startswith("backend/"):
        if any(token in lowered for token in ("login", "logout", "auth handler", "auth route", "auth_bp")):
            canonical_ids.append("auth_handler")
        if any(token in lowered for token in ("session", "login", "logout", "bootstrap", "current_user", "/me")):
            canonical_ids.append("chat_auth_bootstrap")
        if "session" in lowered:
            canonical_ids.append("backend_session_resolver")
    elif record.location.startswith("frontend/"):
        canonical_ids.append("frontend_auth_store")
    if not canonical_ids:
        return [record]
    canonicalized: list[ContractRecord] = []
    for canonical_id in canonical_ids:
        updated_details = dict(details)
        if canonical_id != semantic_identifier:
            updated_details.setdefault("semantic_identifier", semantic_identifier)
        canonicalized.append(
            record.model_copy(
                update={
                    "identifier": canonical_id,
                    "details": updated_details,
                }
            )
        )
    return canonicalized


def _canonicalize_tool_target_contracts(
    *,
    record: ContractRecord,
    content: str,
) -> list[ContractRecord]:
    if _is_noise_tool_target_path(record.location):
        return []
    semantic_identifier = str(record.identifier or "")
    api_surface = [
        _normalize_contract_endpoint_identifier(str(item or ""))
        for item in (record.details or {}).get("api_surface") or []
        if str(item or "").strip()
    ]
    lowered = " ".join(
        [
            semantic_identifier.lower(),
            record.location.lower(),
            json.dumps(record.details, ensure_ascii=False).lower(),
            content.lower(),
            " ".join(api_surface).lower(),
        ]
    )
    roles: list[str] = []
    has_lookup_surface = any(
        path in {"/api/orders/", "/api/orders/{order_id}/"}
        for path in api_surface
    )
    has_action_surface = any("actions" in path or path.endswith(("/cancel", "/refund", "/exchange")) for path in api_surface)
    if any(
        token in lowered
        for token in (
            "order_lookup",
            "list_orders",
            "get_order_status",
            "order_read",
            "list all orders",
            "get_order_detail",
            "order_list",
            "order_detail",
            "serialize_order",
            "can_lookup",
        )
    ) or has_lookup_surface:
        roles.append("order_lookup")
    if any(
        token in lowered
        for token in (
            "order_action",
            "cancel",
            "refund",
            "exchange",
            "management_routes",
            "modify order",
            "order_action",
        )
    ) or has_action_surface:
        roles.append("order_action")
    if "management_routes" in lowered or (has_lookup_surface and has_action_surface):
        roles = ["order_lookup", "order_action"]
    roles = list(dict.fromkeys(roles))
    if not roles:
        return []
    canonicalized: list[ContractRecord] = []
    for role in roles:
        updated_details = dict(record.details)
        if role != semantic_identifier:
            updated_details.setdefault("semantic_identifier", semantic_identifier)
        if role == "order_lookup":
            updated_details.setdefault("tool_name", "list_orders")
        if role == "order_action":
            updated_details.setdefault("tool_name", "cancel|refund|exchange")
        canonicalized.append(
            record.model_copy(
                update={
                    "identifier": role,
                    "details": updated_details,
                }
            )
        )
    return canonicalized


def _is_noise_tool_target_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.endswith(
        (
            "/__init__.py",
            "/admin.py",
            "/apps.py",
            "/settings.py",
            "/seed.py",
        )
    )


def _canonicalize_endpoint_contract(
    *,
    record: ContractRecord,
    endpoint_record: _EndpointCatalogRecord,
) -> ContractRecord:
    details = dict(record.details)
    details.update(
        {
            "path": endpoint_record.path,
            "http_method": endpoint_record.http_method,
            "source_kind": endpoint_record.source_kind,
        }
    )
    if endpoint_record.blueprint_symbol:
        details["blueprint_symbol"] = endpoint_record.blueprint_symbol
    if endpoint_record.local_path:
        details["local_path"] = endpoint_record.local_path
    if record.identifier != endpoint_record.path:
        details["semantic_identifier"] = record.identifier
    evidence_refs = list(
        dict.fromkeys([endpoint_record.source_path, *record.evidence_refs])
    )
    return record.model_copy(
        update={
            "identifier": endpoint_record.path,
            "location": endpoint_record.source_path,
            "details": details,
            "evidence_refs": evidence_refs,
        }
    )


def _is_path_like_endpoint(value: str) -> bool:
    text = str(value or "").strip()
    return text.startswith("/") or "/" in text


def _is_route_definition(*, path: Path, text: str) -> bool:
    if path.suffix != ".py":
        return False
    return any(token in text for token in ("urlpatterns", "register_blueprint(", "include_router(", "APIRouter(", "@router.", "@app.route(", ".route("))


def _is_auth_component(*, path: Path, text: str) -> bool:
    relative = path.as_posix().lower()
    if path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return False
    if any(token in relative for token in ("/tests.py", "/test_", "/__tests__/")):
        return False
    if any(token in relative for token in ("auth", "login", "context", "session", "users/views", "users/router")):
        return True
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("sessionstorage", "access_token", "authorization", "fetchme", "get_current_user", "sessiontoken", "login(")
    )


def _is_model_candidate(*, path: Path, text: str) -> bool:
    relative = path.as_posix().lower()
    if path.suffix != ".py":
        return False
    return (
        relative.endswith("models.py")
        or "__tablename__" in text
        or "models.Model" in text
        or "CREATE TABLE" in text
    )


def _is_api_client(*, path: Path, text: str) -> bool:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return False
    relative = path.as_posix().lower()
    return "/api/" in relative or "fetch(" in text or "axios" in text


def _is_app_shell(*, path: Path, text: str) -> bool:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return False
    relative = path.as_posix().lower()
    return relative.endswith((
        "frontend/src/app.js",
        "frontend/src/app.jsx",
        "frontend/src/app.vue",
        "frontend/app/layout.tsx",
        "frontend/app/page.tsx",
    )) or "function App" in text or "<router-view" in text or "AuthProvider" in text


def _is_router_boundary(*, path: Path, text: str) -> bool:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return False
    return any(token in text for token in ("<Routes", "BrowserRouter", "createRouter(", "<router-view", "useRouter(", "router.push("))


def _is_widget_mount(*, path: Path, text: str) -> bool:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return False
    relative = path.as_posix().lower()
    return "chatbot" in relative or "widget" in relative or "fab" in relative or _is_app_shell(path=path, text=text)


def _is_order_target(*, path: Path, text: str) -> bool:
    normalized_path = path.as_posix().lower()
    if "/backend/" in normalized_path:
        relative = f"backend/{normalized_path.split('/backend/', 1)[1]}"
    else:
        relative = normalized_path
    if path.suffix != ".py":
        return False
    if not relative.startswith("backend/"):
        return False
    if "/migrations/" in relative or relative.endswith(("/tests.py", "/urls.py")):
        return False
    if relative.endswith(("/__init__.py", "/admin.py", "/apps.py", "/settings.py", "/seed.py")):
        return False
    if any(
        token in relative
        for token in (
            "/orders/",
            "/order.py",
            "/orders.py",
            "/routes/order",
            "/router/orders/",
            "/services/order",
            "/repositories/order",
        )
    ):
        return True
    lowered = text.lower()
    if "order" not in lowered:
        return False
    if not any(
        token in relative
        for token in (
            "/views.py",
            "/service.py",
            "/services/",
            "/router/",
            "/routes/",
            "/repository",
            "/crud.py",
            "/models.py",
        )
    ):
        return False
    return any(
        token in lowered
        for token in (
            "order_list",
            "order_detail",
            "order_action",
            "available_actions",
            "serialize_order",
            "cancel",
            "refund",
            "exchange",
            "order.objects",
        )
    )


def _is_service_candidate(relative: str) -> bool:
    lowered = relative.lower()
    return lowered.endswith(("services.py", "service.py")) or "/services/" in lowered


def _is_repository_candidate(relative: str) -> bool:
    lowered = relative.lower()
    return lowered.endswith(("crud.py", "repository.py", "repositories.py")) or "/repositories/" in lowered


def _promote_candidates(
    candidates: list[PathCandidate],
    *,
    preferred_suffixes: list[str],
) -> list[PathCandidate]:
    def _preference_rank(path: str) -> int:
        for index, suffix in enumerate(preferred_suffixes):
            if path.endswith(suffix):
                return index
        return len(preferred_suffixes)

    return sorted(
        candidates,
        key=lambda item: (
            _preference_rank(item.path),
            len(Path(item.path).parts),
            item.path,
        ),
    )


def _candidate(path: str, reason: str) -> PathCandidate:
    return PathCandidate(path=path, reason=reason, source="deterministic", evidence_refs=[path])


def _dedupe_candidates(items: list[PathCandidate]) -> list[PathCandidate]:
    seen: set[str] = set()
    deduped: list[PathCandidate] = []
    for item in items:
        if not item.path or item.path in seen:
            continue
        seen.add(item.path)
        deduped.append(item)
    return deduped


def _dedupe_contracts(records: list[ContractRecord]) -> list[ContractRecord]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ContractRecord] = []
    for record in records:
        key = (record.identifier, record.kind, record.location)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _iter_text_files(root: Path) -> Iterable[tuple[Path, str]]:
    ignore_matcher = OnboardingIgnoreMatcher(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not ignore_matcher.includes(path):
            continue
        if path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        yield path, text


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_excerpt(path: Path, *, max_chars: int = 2400) -> str:
    text = _safe_read_text(path)
    if len(text) <= max_chars:
        return text.strip()
    return text[:max_chars].strip()


def _summarize_excerpt(*, path: str, kind: str, content: str) -> str:
    lowered = content.lower()
    if kind == "route_definition":
        if "include_router" in lowered or "@router." in lowered:
            return "fastapi route registration and endpoint decorators"
        if "register_blueprint" in lowered or ".route(" in lowered:
            return "flask blueprint registration and route handlers"
        if "urlpatterns" in lowered or "path(" in lowered:
            return "django url registration and endpoint mapping"
    if kind == "auth_component":
        return "auth bootstrap, login, or session resolution logic"
    if kind == "order_target":
        return "order domain handler or service target"
    if kind == "database_model":
        return "database model or table definition"
    if kind in {"schema", "serializer"}:
        return "request and response contract definition"
    if kind == "api_client":
        return "frontend API transport and host endpoint usage"
    if kind == "app_shell":
        return "frontend application shell and widget mount boundary"
    return f"evidence read from {path}"


def _normalize_endpoint_template(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", normalized)
    normalized = re.sub(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", normalized)
    normalized = re.sub(r"/+", "/", normalized)
    return normalized


def _extract_contract_endpoint_methods(value: str) -> list[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return []
    match = re.match(r"^(?P<methods>[A-Z]+(?:\|[A-Z]+)*)\s+(?P<path>/.*)$", normalized)
    if not match:
        return []
    methods: list[str] = []
    for token in (match.group("methods") or "").split("|"):
        method = token.strip().upper()
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"} and method not in methods:
            methods.append(method)
    return methods


def _normalize_contract_endpoint_identifier(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    had_method_prefix = bool(re.match(r"^[A-Z]+(?:\|[A-Z]+)*\s+/", normalized))
    normalized = re.sub(r"^[A-Z]+(?:\|[A-Z]+)*\s+", "", normalized)
    normalized = re.sub(r"\s+\((?:frontend|backend)\s+client\)$", "", normalized, flags=re.IGNORECASE)
    if not had_method_prefix and not normalized.startswith("/"):
        return normalized
    return _normalize_endpoint_template(normalized)


def _join_url_parts(prefix: str, suffix: str) -> str:
    prefix_value = _normalize_endpoint_template(prefix)
    suffix_value = _normalize_endpoint_template(suffix)
    if not prefix_value:
        return suffix_value
    if not suffix_value or suffix_value == "/":
        return prefix_value
    return _normalize_endpoint_template(f"{prefix_value.rstrip('/')}/{suffix_value.lstrip('/')}")


def _django_module_name(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("backend/"):
        normalized = normalized[len("backend/") :]
    normalized = normalized.removesuffix(".py")
    return normalized.replace("/", ".")


def _looks_like_auth_content(content: str) -> bool:
    lowered = content.lower()
    return any(
        token in lowered
        for token in ("login", "auth", "token", "session", "current_user", "users/me", "authorization")
    )
