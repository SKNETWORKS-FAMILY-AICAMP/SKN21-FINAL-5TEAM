import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

import pytest

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle, build_analysis_snapshot
from chatbot.src.onboarding_v2.models.analysis import (
    AnalysisBundle,
    AnalysisGraph,
    AnalysisSnapshot,
    BackendSeams,
    CandidateSet,
    ContractRecord,
    DomainIntegration,
    FrontendSeams,
    FrameworkProfile,
    PathCandidate,
    RepoProfile,
    RetrievalPlan,
    VerifiedContracts,
    WorkspaceProfile,
)
from chatbot.src.onboarding_v2.planning import build_integration_plan, build_planning_bundle


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


def _analysis_bundle_from_snapshot(snapshot: AnalysisSnapshot) -> AnalysisBundle:
    valid_candidates = [
        candidate.path
        for candidate in snapshot.domain_integration.order_bridge_targets
        if candidate.path
        and not candidate.path.endswith(("/urls.py", "/tests.py"))
        and "/migrations/" not in candidate.path
    ]
    lookup_target = next(
        (
            path
            for path in valid_candidates
            if any(token in path.lower() for token in ("lookup", "status", "list", "detail", "query", "read"))
        ),
        valid_candidates[0] if valid_candidates else "backend/orders/views.py",
    )
    action_target = next(
        (
            path
            for path in valid_candidates
            if any(token in path.lower() for token in ("action", "update", "cancel", "refund", "exchange", "modify", "mutat", "command", "handler", "write"))
        ),
        valid_candidates[0] if valid_candidates else "backend/orders/views.py",
    )
    return AnalysisBundle(
        workspace_profile=WorkspaceProfile(root=snapshot.repo_profile.source_root),
        framework_profile=FrameworkProfile(
            backend_framework=snapshot.repo_profile.backend_framework,
            frontend_framework=snapshot.repo_profile.frontend_framework,
            auth_style=snapshot.repo_profile.auth_style,
        ),
        retrieval_plan=RetrievalPlan(),
        candidate_set=CandidateSet(
            route_definitions=list(snapshot.backend_seams.route_registration_points),
            auth_components=list(snapshot.backend_seams.auth_source_candidates),
            api_clients=list(snapshot.frontend_seams.api_client_candidates),
            app_shells=list(snapshot.frontend_seams.app_shell_candidates),
            router_boundaries=list(snapshot.frontend_seams.router_boundary_candidates),
            widget_mounts=list(snapshot.frontend_seams.widget_mount_candidates),
            order_targets=list(snapshot.domain_integration.order_bridge_targets),
        ),
        verified_contracts=VerifiedContracts(
            tool_targets=[
                ContractRecord(
                    identifier="order_lookup",
                    kind="tool_target",
                    location=lookup_target,
                    evidence_refs=[lookup_target],
                ),
                ContractRecord(
                    identifier="order_action",
                    kind="tool_target",
                    location=action_target,
                    evidence_refs=[action_target],
                ),
            ]
        ),
        analysis_graph=AnalysisGraph(),
        unresolved_ambiguities=list(snapshot.ambiguity.open_questions),
        snapshot=snapshot.model_copy(
            update={
                "domain_integration": snapshot.domain_integration.model_copy(
                    update={
                        "auth_validation_endpoint": snapshot.domain_integration.auth_validation_endpoint or "/api/users/me/",
                        "current_user_endpoint": snapshot.domain_integration.current_user_endpoint or "/api/users/me/",
                        "product_search_endpoint": snapshot.domain_integration.product_search_endpoint or "/api/products/",
                        "order_list_endpoint": snapshot.domain_integration.order_list_endpoint or "/api/orders/",
                        "order_detail_endpoint": snapshot.domain_integration.order_detail_endpoint or "/api/orders/{order_id}/",
                        "order_action_endpoint": snapshot.domain_integration.order_action_endpoint or "/api/orders/{order_id}/actions/",
                    }
                )
            }
        ),
    )


def test_planner_selects_food_strategies():
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    snapshot = analysis_bundle.snapshot
    planning_bundle = build_planning_bundle(
        snapshot=snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    plan = planning_bundle.integration_plan

    assert plan.host_backend.strategy == "django_project_urlconf_import_view"
    assert plan.host_backend.route_target == "backend/foodshop/urls.py"
    assert plan.host_backend.auth_handler_source == "backend/users/views.py"
    assert plan.host_backend.site_id == "food"
    assert plan.host_backend.order_lookup_target == "backend/orders/views.py"
    assert plan.host_backend.order_action_target == "backend/orders/views.py"
    assert plan.host_backend.exchange_strategy == "augment_existing_order_action_endpoint"
    assert plan.host_backend.supported_order_tools == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]
    assert plan.host_frontend.mount_target == "frontend/src/App.js"
    assert plan.host_frontend.api_client_target == "frontend/src/api/api.js"
    assert plan.host_frontend.chatbot_server_base_url == "http://localhost:8100"
    assert (
        plan.host_frontend.chatbot_server_base_url_expression
        == 'process.env.REACT_APP_CHATBOT_SERVER_BASE_URL || "http://127.0.0.1:8100"'
    )
    assert plan.chatbot_bridge.site_key == "food"
    assert plan.chatbot_bridge.adapter_package == "src/adapters/generated/food"
    assert plan.chatbot_bridge.auth_validation_endpoint == "/api/users/me/"
    assert plan.chatbot_bridge.current_user_endpoint == "/api/users/me/"
    assert plan.chatbot_bridge.product_search_endpoint == "/api/products/"
    assert plan.chatbot_bridge.order_list_endpoint == "/api/orders/"
    assert plan.chatbot_bridge.order_detail_endpoint == "/api/orders/{order_id}/"
    assert plan.chatbot_bridge.order_action_endpoint == "/api/orders/{order_id}/actions/"
    assert plan.chatbot_bridge.auth_transport == "session_token_cookie"
    assert plan.chatbot_bridge.response_mapping_profile == "site_a"
    assert plan.chatbot_bridge.request_field_mappings == {
        "action": "action",
        "reason": "reason",
        "new_option_id": "new_option_id",
    }
    assert plan.chatbot_bridge.supported_tools == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]
    assert planning_bundle.target_bindings
    assert planning_bundle.repair_hints
    assert plan.host_backend.order_action_request_field == "action"
    assert plan.host_backend.order_action_new_option_field == "new_option_id"
    assert plan.host_backend.order_action_response_serializer == "serialize_order"
    assert plan.host_backend.exchange_status_transition == "EXCHANGE_REQUESTED"


def test_planner_ignores_invalid_order_bridge_candidates_and_falls_back():
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="food",
            source_root=str(ROOT / "food"),
            backend_framework="django",
            frontend_framework="react",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(
            order_bridge_targets=[
                PathCandidate(path="backend/foodshop/urls.py", reason="order bridge target candidate"),
                PathCandidate(path="backend/orders/tests.py", reason="order bridge target candidate"),
                PathCandidate(path="backend/orders/migrations/0001_initial.py", reason="order bridge target candidate"),
            ]
        ),
    )

    plan = build_integration_plan(
        snapshot,
        analysis_bundle=_analysis_bundle_from_snapshot(snapshot),
        chatbot_server_base_url="http://localhost:8100",
    )

    assert plan.host_backend.order_lookup_target == "backend/orders/views.py"
    assert plan.host_backend.order_action_target == "backend/orders/views.py"


def test_planner_prefers_valid_generic_order_seam_over_fallback():
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="food",
            source_root=str(ROOT / "food"),
            backend_framework="django",
            frontend_framework="react",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(
            order_bridge_targets=[
                PathCandidate(
                    path="backend/custom/orders.py",
                    reason="order bridge target candidate",
                ),
            ]
        ),
    )

    plan = build_integration_plan(
        snapshot,
        analysis_bundle=_analysis_bundle_from_snapshot(snapshot),
        chatbot_server_base_url="http://localhost:8100",
    )

    assert plan.host_backend.order_lookup_target == "backend/custom/orders.py"
    assert plan.host_backend.order_action_target == "backend/custom/orders.py"


def test_planner_can_split_lookup_and_action_targets_from_generic_candidates():
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="food",
            source_root=str(ROOT / "food"),
            backend_framework="django",
            frontend_framework="react",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(
            order_bridge_targets=[
                PathCandidate(
                    path="backend/orders/lookup.py",
                    reason="order bridge target candidate",
                ),
                PathCandidate(
                    path="backend/orders/actions.py",
                    reason="order bridge target candidate",
                ),
                PathCandidate(
                    path="backend/orders/views.py",
                    reason="order bridge target candidate",
                ),
            ]
        ),
    )

    plan = build_integration_plan(
        snapshot,
        analysis_bundle=_analysis_bundle_from_snapshot(snapshot),
        chatbot_server_base_url="http://localhost:8100",
    )

    assert plan.host_backend.order_lookup_target == "backend/orders/lookup.py"
    assert plan.host_backend.order_action_target == "backend/orders/actions.py"


def test_build_integration_plan_requires_analysis_bundle():
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")

    with pytest.raises(ValueError, match="analysis_bundle is required"):
        build_integration_plan(
            snapshot,
            chatbot_server_base_url="http://localhost:8100",
        )


def test_planner_accepts_bilyeo_strict_coverage_with_verified_flask_endpoints():
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")

    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    plan = planning_bundle.integration_plan

    assert plan.host_backend.strategy == "flask_app_register_blueprint"
    assert plan.host_backend.route_target == "backend/app.py"
    assert plan.host_backend.order_lookup_target == "backend/routes/order.py"
    assert plan.host_backend.order_action_target == "backend/routes/order.py"
    assert plan.host_backend.auth_handler_source == "backend/routes/auth.py"
