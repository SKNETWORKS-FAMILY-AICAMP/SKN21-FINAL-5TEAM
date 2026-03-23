import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.models.analysis import (
    AnalysisSnapshot,
    BackendSeams,
    DomainIntegration,
    FrontendSeams,
    PathCandidate,
    RepoProfile,
)
from chatbot.src.onboarding_v2.planning import build_integration_plan


def test_planner_selects_food_strategies():
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(
        snapshot,
        chatbot_server_base_url="http://localhost:8100",
    )

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
    assert plan.chatbot_bridge.supported_tools == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]


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
        chatbot_server_base_url="http://localhost:8100",
    )

    assert plan.host_backend.order_lookup_target == "backend/orders/lookup.py"
    assert plan.host_backend.order_action_target == "backend/orders/actions.py"
