from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.planning import (
    BackendWiringPlan,
    DomainAdaptersPlan,
    FrontendIntegrationPlan,
    IntegrationPlan,
    PlanningNotes,
    SupportingArtifactSpec,
)


def build_integration_plan(snapshot: AnalysisSnapshot) -> IntegrationPlan:
    backend_framework = snapshot.repo_profile.backend_framework
    frontend_framework = snapshot.repo_profile.frontend_framework
    route_target = _choose_route_target(snapshot)
    auth_source = _choose_auth_source(snapshot)
    mount_target = _choose_mount_target(snapshot)
    api_client_target = _choose_api_client_target(snapshot, fallback=mount_target)
    generated_handler_path = _choose_generated_handler_path(backend_framework)

    backend_strategy = {
        "django": "django_project_urlconf_import_view",
        "flask": "flask_app_register_blueprint",
        "fastapi": "fastapi_include_router",
    }.get(backend_framework, "django_project_urlconf_import_view")
    mount_strategy = {
        "react": "react_app_shell_outside_routes",
        "vue": "react_app_shell_outside_routes",
    }.get(frontend_framework, "react_app_shell_outside_routes")
    api_strategy = {
        "react": "react_api_client_augment_existing",
        "vue": "react_api_client_augment_existing",
    }.get(frontend_framework, "react_api_client_augment_existing")

    assumptions = []
    if backend_framework == "django":
        assumptions.append("chat auth bridge will be materialized in backend/chat_auth.py")
    if mount_target == api_client_target:
        assumptions.append("frontend api support falls back to app shell because no dedicated api client was found")

    supporting_artifacts = []
    if generated_handler_path:
        supporting_artifacts.append(
            SupportingArtifactSpec(
                path=generated_handler_path,
                kind="python_module",
                reason="generated chat auth bridge module",
            )
        )

    domain_adapters = DomainAdaptersPlan(
        product_adapter_target=None,
        order_adapter_target=(
            snapshot.domain_integration.order_bridge_targets[0].path
            if snapshot.domain_integration.order_bridge_targets
            else None
        ),
        tool_registry_target=(
            snapshot.backend_seams.tool_registry_candidates[0].path
            if snapshot.backend_seams.tool_registry_candidates
            else None
        ),
    )

    return IntegrationPlan(
        backend_wiring=BackendWiringPlan(
            strategy=backend_strategy,
            route_target=route_target,
            import_target=route_target,
            auth_handler_source=auth_source,
            generated_handler_path=generated_handler_path,
            chat_auth_contract_path="/api/chat/auth-token",
        ),
        frontend_integration=FrontendIntegrationPlan(
            mount_strategy=mount_strategy,
            mount_target=mount_target,
            router_boundary=(
                snapshot.frontend_seams.router_boundary_candidates[0].path
                if snapshot.frontend_seams.router_boundary_candidates
                else mount_target
            ),
            api_strategy=api_strategy,
            api_client_target=api_client_target,
            auth_bootstrap_path="/api/chat/auth-token",
        ),
        domain_adapters=domain_adapters,
        supporting_artifacts=supporting_artifacts,
        planning_notes=PlanningNotes(
            assumptions=assumptions,
            ambiguities=list(snapshot.ambiguity.open_questions),
            llm_rationale=[],
        ),
    )


def _choose_route_target(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.backend_seams.route_registration_points]
    if not candidates:
        return "backend/foodshop/urls.py"
    preferred = sorted(
        candidates,
        key=lambda value: (
            0 if value.endswith(("foodshop/urls.py", "config/urls.py", "project/urls.py")) else 1,
            len(Path(value).parts),
            value,
        ),
    )
    return preferred[0]


def _choose_auth_source(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.backend_seams.auth_source_candidates]
    preferred = [candidate for candidate in candidates if candidate.endswith("users/views.py")]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return "backend/users/views.py"


def _choose_mount_target(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.frontend_seams.app_shell_candidates]
    preferred = [candidate for candidate in candidates if candidate.endswith("frontend/src/App.js")]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    if snapshot.frontend_seams.widget_mount_candidates:
        return snapshot.frontend_seams.widget_mount_candidates[0].path
    return "frontend/src/App.js"


def _choose_api_client_target(snapshot: AnalysisSnapshot, *, fallback: str) -> str:
    candidates = [candidate.path for candidate in snapshot.frontend_seams.api_client_candidates]
    preferred = [
        candidate
        for candidate in candidates
        if candidate.endswith(("frontend/src/api/api.js", "src/api/api.js"))
    ]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return fallback


def _choose_generated_handler_path(backend_framework: str) -> str | None:
    if backend_framework == "django":
        return "backend/chat_auth.py"
    if backend_framework in {"flask", "fastapi"}:
        return "chat_auth.py"
    return None
