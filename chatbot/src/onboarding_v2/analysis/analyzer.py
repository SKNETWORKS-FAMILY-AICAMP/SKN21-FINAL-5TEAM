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
    artifact_refs: list[ArtifactRef] | None = None,
) -> AnalysisBundle:
    root = _resolve_root(source_root)
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

        verified_contracts, rejected_claims, unresolved_ambiguities = _verify_contracts(
            root=root,
            framework_profile=framework_profile,
            candidate_set=current_candidate_set,
            contracts=extracted_contracts,
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
    snapshot = _build_snapshot_from_bundle(
        site=site,
        root=root,
        workspace_profile=workspace_profile,
        framework_profile=framework_profile,
        candidate_set=current_candidate_set,
        verified_contracts=verified_contracts,
        unresolved_ambiguities=unresolved_ambiguities,
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
    manifest_path = "site-manifest.json" if (root / "site-manifest.json").exists() else None
    return WorkspaceProfile(
        root=str(root),
        backend_root=backend_root,
        frontend_root=frontend_root,
        manifest_path=manifest_path,
    )


def _build_framework_profile(*, root: Path) -> FrameworkProfile:
    manifest = _load_manifest(root)
    backend_framework = _normalize_backend_framework(
        manifest.get("backend_framework", {}).get("name")
        if isinstance(manifest.get("backend_framework"), dict)
        else None,
        root=root,
    )
    frontend_framework = _normalize_frontend_framework(
        manifest.get("frontend_framework", {}).get("name")
        if isinstance(manifest.get("frontend_framework"), dict)
        else None,
        root=root,
    )
    auth_style = _normalize_auth_style(
        manifest.get("auth", {}).get("auth_type") if isinstance(manifest.get("auth"), dict) else None,
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
            "framework profile derived from manifest plus deterministic repo fingerprinting",
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


def _sanitize_evidence_packets(
    *,
    packets: list[EvidencePacket],
    fallback: list[EvidencePacket],
    root: Path,
) -> list[EvidencePacket]:
    sanitized: list[EvidencePacket] = []
    seen: set[str] = set()
    for packet in [*packets, *fallback]:
        if not packet.path or packet.packet_id in seen or not (root / packet.path).exists():
            continue
        seen.add(packet.packet_id)
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
) -> tuple[VerifiedContracts, list[RejectedClaim], list[str]]:
    route_catalog = _build_route_catalog(
        root=root,
        framework_profile=framework_profile,
        candidate_set=candidate_set,
    )
    table_catalog = _build_table_catalog(
        root=root,
        framework_profile=framework_profile,
        candidate_set=candidate_set,
    )
    api_client_catalog = _build_api_client_catalog(root=root, candidate_set=candidate_set)

    verified = VerifiedContracts()
    rejected: list[RejectedClaim] = []
    ambiguities: list[str] = []

    for record in contracts.database_entities:
        text = _safe_read_text(root / record.location)
        if (root / record.location).exists() and (
            record.identifier in table_catalog or record.identifier in text or record.location.endswith("models.py")
        ):
            verified.database_entities.append(record)
        else:
            rejected.append(
                RejectedClaim(
                    identifier=record.identifier,
                    kind=record.kind,
                    reason="database entity could not be verified from models or table catalog",
                    evidence_refs=list(record.evidence_refs),
                )
            )

    for record in contracts.api_endpoints:
        normalized = _normalize_endpoint_template(record.identifier)
        if normalized in route_catalog or normalized in api_client_catalog:
            verified.api_endpoints.append(record)
        else:
            rejected.append(
                RejectedClaim(
                    identifier=record.identifier,
                    kind=record.kind,
                    reason="api endpoint could not be verified from route or client catalogs",
                    evidence_refs=list(record.evidence_refs),
                )
            )

    for record in contracts.auth_components:
        content = _safe_read_text(root / record.location)
        if (root / record.location).exists() and _looks_like_auth_content(content):
            verified.auth_components.append(record)
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
            verified.tool_targets.append(record)
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
        ),
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
                *(workspace_profile.manifest_path and [workspace_profile.manifest_path] or []),
                *backend_entrypoints,
                *frontend_entrypoints,
            ],
            confidence_notes=list(dict.fromkeys([
                *framework_profile.confidence_notes,
                "snapshot derived from verified contracts and analysis graph",
            ])),
        ),
    )


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
    identifiers = list(dict.fromkeys([*route_catalog, *api_client_catalog]))
    records: list[ContractRecord] = []
    for identifier in identifiers:
        domain = "order" if "order" in identifier.lower() else "product" if "product" in identifier.lower() else "auth_bootstrap" if "chat/auth-token" in identifier else "auth" if "login" in identifier.lower() or "users/me" in identifier.lower() else "generic"
        location = _find_endpoint_location(identifier=identifier, candidate_set=candidate_set, root=root)
        records.append(
            ContractRecord(
                identifier=identifier,
                kind="api_endpoint",
                location=location,
                owner="deterministic",
                details={"domain": domain},
                evidence_refs=[location] if location else [],
            )
        )
    bootstrap_source = _choose_backend_auth_source(candidate_set)
    records.append(
        ContractRecord(
            identifier="/api/chat/auth-token",
            kind="api_endpoint",
            location=bootstrap_source,
            owner="deterministic",
            details={"domain": "auth_bootstrap"},
            evidence_refs=[bootstrap_source] if bootstrap_source else [],
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
) -> list[str]:
    if framework_profile.backend_framework == "django":
        return _build_django_route_catalog(root=root, route_candidates=candidate_set.route_definitions)
    if framework_profile.backend_framework == "flask":
        return _build_flask_route_catalog(root=root, route_candidates=candidate_set.route_definitions)
    if framework_profile.backend_framework == "fastapi":
        return _build_fastapi_route_catalog(root=root, route_candidates=candidate_set.route_definitions)
    return []


def _build_django_route_catalog(*, root: Path, route_candidates: list[PathCandidate]) -> list[str]:
    path_pattern = re.compile(r'path\(\s*[\'"]([^\'"]*)[\'"]')
    include_pattern = re.compile(r'path\(\s*[\'"]([^\'"]*)[\'"].*include\(\s*[\'"]([^\'"]+)[\'"]\)')
    module_prefixes: dict[str, str] = {}
    file_patterns: dict[str, list[str]] = {}
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        patterns = [match.group(1) for match in path_pattern.finditer(text)]
        file_patterns[candidate.path] = patterns
        for match in include_pattern.finditer(text):
            module_prefixes[match.group(2)] = _normalize_endpoint_template(match.group(1))

    endpoints: list[str] = []
    for candidate in route_candidates:
        module_name = _django_module_name(candidate.path)
        prefix = module_prefixes.get(module_name)
        for pattern in file_patterns.get(candidate.path, []):
            if pattern == "" and prefix:
                endpoints.append(prefix)
                continue
            normalized = _normalize_endpoint_template(pattern)
            if prefix and candidate.path.endswith("/urls.py") and prefix != normalized:
                endpoints.append(_join_url_parts(prefix, normalized))
            else:
                endpoints.append(normalized)
    return list(dict.fromkeys(endpoint for endpoint in endpoints if endpoint))


def _build_flask_route_catalog(*, root: Path, route_candidates: list[PathCandidate]) -> list[str]:
    register_pattern = re.compile(r"register_blueprint\(\s*([a-zA-Z0-9_]+),\s*url_prefix=['\"]([^'\"]+)['\"]")
    route_pattern = re.compile(r"@([a-zA-Z0-9_]+)\.route\(\s*['\"]([^'\"]+)['\"]")
    prefixes: dict[str, str] = {}
    endpoints: list[str] = []
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        for match in register_pattern.finditer(text):
            prefixes[match.group(1)] = _normalize_endpoint_template(match.group(2))
    for candidate in route_candidates:
        text = _safe_read_text(root / candidate.path)
        for match in route_pattern.finditer(text):
            blueprint = match.group(1)
            prefix = prefixes.get(blueprint, "")
            endpoints.append(_join_url_parts(prefix, match.group(2)))
    return list(dict.fromkeys(endpoint for endpoint in endpoints if endpoint))


def _build_fastapi_route_catalog(*, root: Path, route_candidates: list[PathCandidate]) -> list[str]:
    import_pattern = re.compile(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+router\s+as\s+([a-zA-Z0-9_]+)")
    include_pattern = re.compile(r"include_router\(\s*([a-zA-Z0-9_]+),\s*prefix=['\"]([^'\"]+)['\"]")
    decorator_pattern = re.compile(r"@([a-zA-Z0-9_]+)\.(?:get|post|patch|put|delete)\(\s*['\"]([^'\"]+)['\"]")
    prefixes: dict[str, str] = {}
    alias_modules: dict[str, str] = {}
    endpoints: list[str] = []
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
            prefix = prefixes.get(router_name, inferred_prefix)
            endpoints.append(_join_url_parts(prefix, match.group(2)))
    return list(dict.fromkeys(endpoint for endpoint in endpoints if endpoint))


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


def _build_api_client_catalog(*, root: Path, candidate_set: CandidateSet) -> list[str]:
    endpoint_pattern = re.compile(r"['\"](/api/[^'\"]+|/orders[^'\"]+|/users/[^'\"]+|/products[^'\"]+)['\"]")
    catalog: list[str] = []
    for candidate in candidate_set.api_clients:
        text = _safe_read_text(root / candidate.path)
        for match in endpoint_pattern.finditer(text):
            catalog.append(_normalize_endpoint_template(match.group(1)))
    return list(dict.fromkeys(catalog))


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
    if normalized:
        return normalized
    for _path, text in _iter_text_files(root):
        lowered = text.lower()
        if "authorization" in lowered and "bearer" in lowered:
            return "jwt_bearer"
        if "session_token" in lowered or "cookie" in lowered:
            return "session_cookie"
    return "unknown"


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
    relative = path.as_posix().lower()
    if path.suffix != ".py":
        return False
    if "/migrations/" in relative or relative.endswith(("/tests.py", "/urls.py")):
        return False
    return "order" in relative or "order" in text.lower()


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
    normalized = re.sub(r"/+", "/", normalized)
    return normalized


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
