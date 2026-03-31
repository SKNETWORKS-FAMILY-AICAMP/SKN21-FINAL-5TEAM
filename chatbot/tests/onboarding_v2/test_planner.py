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
    RagSourceRecord,
    RagSources,
    VerifiedContracts,
    WorkspaceProfile,
)
from chatbot.src.onboarding_v2.models.planning import ResolvedResponseContract
from chatbot.src.onboarding_v2.planning import planner as planner_module
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
                        "login_endpoint": getattr(snapshot.domain_integration, "login_endpoint", None),
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
    assert plan.host_backend.login_endpoint == "/api/users/login/"
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
    assert plan.chatbot_bridge.auth_transport == "session_cookie"
    assert plan.chatbot_bridge.session_cookie_name == "session_token"
    assert plan.chatbot_bridge.csrf_cookie_name is None
    assert plan.chatbot_bridge.csrf_header_name is None
    assert plan.chatbot_bridge.auth_contract.transport == "session_cookie"
    assert plan.chatbot_bridge.auth_contract.session_cookie_name == "session_token"
    assert plan.chatbot_bridge.response_contract.order_profile == "rest_detail_wrapped_order"
    assert plan.chatbot_bridge.response_contract.order_status_profile == "english_tokens"
    assert plan.chatbot_bridge.order_action_contract.submission_mode == "single_endpoint_json_body"
    assert plan.chatbot_bridge.order_action_contract.request_fields.model_dump(mode="json") == {
        "action": "action",
        "reason": "reason",
        "new_option_id": "new_option_id",
    }
    assert plan.chatbot_bridge.response_mapping_profile == "rest_detail_wrapped_order"
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
            login_endpoint="/api/users/login/",
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
            login_endpoint="/api/users/login/",
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
            login_endpoint="/api/users/login/",
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
    assert plan.host_backend.login_endpoint == "/api/auth/login"
    assert plan.chatbot_bridge.auth_validation_endpoint == "/api/chat/auth-token"
    assert plan.chatbot_bridge.current_user_endpoint == "/api/chat/auth-token"
    assert plan.chatbot_bridge.auth_transport == "bearer_token"
    assert plan.chatbot_bridge.response_contract.user_profile == "wrapped_user"
    assert plan.chatbot_bridge.response_contract.order_profile == "orders_collection_scan"
    assert plan.chatbot_bridge.order_action_contract.submission_mode == "per_action_query_endpoint"
    assert plan.chatbot_bridge.order_action_contract.supported_actions == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]


def test_planner_orders_collection_scan_prefers_per_action_endpoints_over_read_only():
    order_action_contract = planner_module._infer_bridge_order_action_contract(
        domain_integration=DomainIntegration(
            order_action_endpoint="/api/orders/{order_id}/exchange",
            order_action_endpoints={
                "cancel": "/api/orders/{order_id}/cancel",
                "refund": "/api/orders/{order_id}/refund",
                "exchange": "/api/orders/{order_id}/exchange",
            },
        ),
        response_contract=ResolvedResponseContract(
            order_profile="orders_collection_scan",
        ),
    )

    assert order_action_contract.submission_mode == "per_action_query_endpoint"
    assert order_action_contract.supported_actions == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]


def test_planner_orders_collection_scan_uses_single_endpoint_when_shared_mutation_path_exists():
    order_action_contract = planner_module._infer_bridge_order_action_contract(
        domain_integration=DomainIntegration(
            order_action_endpoint="/api/orders/{order_id}/actions",
            order_action_endpoints={},
        ),
        response_contract=ResolvedResponseContract(
            order_profile="orders_collection_scan",
        ),
    )

    assert order_action_contract.submission_mode == "single_endpoint_json_body"
    assert order_action_contract.supported_actions == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]


def test_planner_orders_collection_scan_stays_read_only_when_mutation_surface_is_missing():
    order_action_contract = planner_module._infer_bridge_order_action_contract(
        domain_integration=DomainIntegration(
            order_action_endpoint="",
            order_action_endpoints={},
        ),
        response_contract=ResolvedResponseContract(
            order_profile="orders_collection_scan",
        ),
    )

    assert order_action_contract.submission_mode == "read_only"
    assert order_action_contract.supported_actions == [
        "list_orders",
        "get_order_status",
    ]


def test_planner_infers_user_scoped_order_service_contract():
    contract = planner_module._derive_chatbot_bridge_contract(
        domain_integration=DomainIntegration(
            auth_validation_endpoint="/users/me/",
            current_user_endpoint="/users/me/",
            product_search_endpoint="/products/new",
            order_list_endpoint="/orders/{user_id}/orders",
            order_detail_endpoint="/orders/{user_id}/orders/{order_id}",
            order_action_endpoint="/orders/{user_id}/orders/{order_id}/cancel",
            order_action_endpoints={
                "cancel": "/orders/{user_id}/orders/{order_id}/cancel",
                "refund": "/orders/{user_id}/orders/{order_id}/refund",
            },
        ),
        site_id="site-c-like",
        source_root=ROOT,
        backend_framework="fastapi",
        auth_handler_source="backend/users/views.py",
        auth_style_hint="session_cookie",
    )

    response_contract = contract["response_contract"]
    order_action_contract = contract["order_action_contract"]

    assert response_contract.order_profile == "user_scoped_order_service"
    assert response_contract.order_identifier_mode == "order_number_with_internal_resolution"
    assert order_action_contract.submission_mode == "per_action_query_endpoint"
    assert order_action_contract.supported_actions == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
    ]


def test_planner_infers_cookie_plus_csrf_transport_from_auth_source(tmp_path: Path):
    auth_source = tmp_path / "backend" / "users" / "views.py"
    auth_source.parent.mkdir(parents=True, exist_ok=True)
    auth_source.write_text(
        "from django.http import JsonResponse\n\n"
        'SESSION_COOKIE_NAME = "sessionid"\n'
        'CSRF_COOKIE_NAME = "csrftoken"\n'
        'CSRF_HEADER_NAME = "X-CSRFToken"\n\n'
        "def login(request):\n"
        '    token = request.COOKIES.get(CSRF_COOKIE_NAME) or request.META.get("HTTP_X_CSRFTOKEN")\n'
        '    session_id = request.COOKIES.get(SESSION_COOKIE_NAME)\n'
        "    response = JsonResponse({'ok': True})\n"
        "    if token and session_id:\n"
        "        return response\n"
        '    response.set_cookie(SESSION_COOKIE_NAME, "session-1")\n'
        '    response.set_cookie(CSRF_COOKIE_NAME, "csrf-1")\n'
        "    return response\n",
        encoding="utf-8",
    )

    contract = planner_module._derive_chatbot_bridge_contract(
        domain_integration=DomainIntegration(
            auth_validation_endpoint="/api/users/me/",
            current_user_endpoint="/api/users/me/",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
        ),
        site_id="csrf-shop",
        source_root=tmp_path,
        backend_framework="django",
        auth_handler_source="backend/users/views.py",
        auth_style_hint="cookie_plus_csrf",
    )

    auth_contract = contract["auth_contract"]

    assert auth_contract.transport == "cookie_plus_csrf"
    assert auth_contract.session_cookie_name == "sessionid"
    assert auth_contract.csrf_cookie_name == "csrftoken"
    assert auth_contract.csrf_header_name == "X-CSRFToken"


def test_planner_combines_risk_and_repair_hint_llm_calls(monkeypatch):
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    phases: list[str] = []

    def _fake_invoke_structured_stage(*, phase, response_model, fallback_payload, **kwargs):
        del kwargs
        phases.append(phase)
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(planner_module, "invoke_structured_stage", _fake_invoke_structured_stage)

    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )

    assert "risk-and-repair" in phases
    assert "risk-register" not in phases
    assert "repair-hints" not in phases
    assert planning_bundle.risk_register
    assert planning_bundle.repair_hints


def test_planner_forwards_event_callback_to_all_llm_phases(monkeypatch):
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    callback = lambda payload: payload
    observed: list[tuple[str, object, float | None]] = []

    def _fake_invoke_structured_stage(
        *,
        phase,
        response_model,
        fallback_payload,
        event_callback=None,
        heartbeat_interval_s=None,
        **kwargs,
    ):
        del kwargs
        observed.append((phase, event_callback, heartbeat_interval_s))
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(planner_module, "invoke_structured_stage", _fake_invoke_structured_stage)

    build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        event_callback=callback,
        heartbeat_interval_s=0.05,
    )

    assert [phase for phase, _event_callback, _interval in observed] == [
        "strategy-synthesis",
        "binding-selection",
        "risk-and-repair",
    ]
    assert all(event_callback is callback for _phase, event_callback, _interval in observed)
    assert all(interval == 0.05 for _phase, _event_callback, interval in observed)


def test_planner_uses_snapshot_site_without_manifest(tmp_path: Path):
    source_root = tmp_path / "site"
    frontend_root = source_root / "frontend"
    frontend_root.mkdir(parents=True)
    (frontend_root / "package.json").write_text(
        '{"dependencies":{"react-scripts":"5.0.1"}}\n',
        encoding="utf-8",
    )
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="demo-site",
            source_root=str(source_root),
            backend_framework="django",
            frontend_framework="react",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(
            auth_source_candidates=[
                PathCandidate(path="backend/users/views.py", reason="auth"),
            ],
            route_registration_points=[
                PathCandidate(path="backend/config/urls.py", reason="route registration"),
            ],
        ),
        frontend_seams=FrontendSeams(
            app_shell_candidates=[
                PathCandidate(path="frontend/src/App.js", reason="app shell"),
            ],
            api_client_candidates=[
                PathCandidate(path="frontend/src/api/api.js", reason="api client"),
            ],
            widget_mount_candidates=[
                PathCandidate(path="frontend/src/App.js", reason="widget mount"),
            ],
        ),
        domain_integration=DomainIntegration(
            login_endpoint="/api/auth/login",
            auth_validation_endpoint="/api/auth/me",
            current_user_endpoint="/api/auth/me",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
            order_bridge_targets=[
                PathCandidate(path="backend/orders/views.py", reason="order seam"),
            ],
        ),
    )

    plan = build_integration_plan(
        snapshot,
        analysis_bundle=_analysis_bundle_from_snapshot(snapshot),
        chatbot_server_base_url="http://localhost:8100",
    )

    assert plan.host_backend.site_id == "demo-site"
    assert plan.chatbot_bridge.site_key == "demo-site"


def test_planner_fails_closed_when_login_endpoint_missing():
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
                PathCandidate(path="backend/orders/views.py", reason="order bridge target candidate"),
            ]
        ),
    )

    with pytest.raises(ValueError, match="missing verified host login endpoint for planning"):
        build_integration_plan(
            snapshot,
            analysis_bundle=_analysis_bundle_from_snapshot(snapshot),
            chatbot_server_base_url="http://localhost:8100",
        )


def test_planner_builds_site_scoped_retrieval_index_plan_and_capability_upgrade():
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    rag_sources = RagSources(
        faq=[
            RagSourceRecord(
                path="scripts/faq_crawling.py",
                kind="crawl_script",
                corpus="faq",
                reason="faq crawler",
            )
        ],
        policy=[
            RagSourceRecord(
                path="docs/refund-policy.md",
                kind="markdown_doc",
                corpus="policy",
                reason="policy doc",
            )
        ],
        discovery_image=[
            RagSourceRecord(
                path="scripts/product_crawling.py",
                kind="crawl_script",
                corpus="discovery_image",
                reason="remote image crawler",
            )
        ],
    )
    analysis_bundle = analysis_bundle.model_copy(
        update={
            "rag_sources": rag_sources,
            "snapshot": analysis_bundle.snapshot.model_copy(update={"rag_sources": rag_sources}),
        }
    )

    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )

    retrieval_index_plan = planning_bundle.retrieval_index_plan
    assert retrieval_index_plan.site_slug == "bilyeo"
    assert {item.corpus for item in retrieval_index_plan.corpora} == {
        "faq",
        "policy",
        "discovery_image",
    }
    assert {
        item.collection_alias for item in retrieval_index_plan.corpora
    } == {
        "site_bilyeo__faq",
        "site_bilyeo__policy",
        "site_bilyeo__discovery_image",
    }
    assert all("__run_runtime" in item.build_collection for item in retrieval_index_plan.corpora)
    discovery_plan = next(item for item in retrieval_index_plan.corpora if item.corpus == "discovery_image")
    assert discovery_plan.row_source_strategy == "host_api_fetch"
    assert discovery_plan.row_source_endpoint == planning_bundle.integration_plan.chatbot_bridge.product_search_endpoint
    assert discovery_plan.row_id_field == "product_id"
    assert discovery_plan.row_image_url_field == "image_url"
    assert discovery_plan.pagination_strategy == {
        "type": "page_number",
        "page_param": "page",
        "page_size_param": "page_size",
        "page_size": 100,
        "stop_on": "empty_or_repeated_ids",
    }
    assert planning_bundle.integration_plan.capability_upgrade["capability_profile"] == "order_cs_plus_retrieval"
    assert planning_bundle.integration_plan.host_backend.capability_profile == "order_cs_only"
    assert planning_bundle.integration_plan.host_frontend.capability_profile == "order_cs_only"
    assert planning_bundle.integration_plan.host_frontend.widget_features["image_upload"] is False
    assert planning_bundle.integration_plan.host_frontend.enabled_retrieval_corpora == []


def test_planner_uses_host_python_fetch_for_db_backed_faq_sources():
    retrieval_index_plan = planner_module._build_retrieval_index_plan(
        site_id="bilyeo",
        rag_sources=RagSources(
            faq=[
                RagSourceRecord(
                    path="backend/models/faq.py",
                    kind="code_file",
                    corpus="faq",
                    reason="db-backed faq model",
                    details={"source_surface": "db_table"},
                )
            ]
        ),
        run_id="runtime",
        product_search_endpoint="/api/products",
    )

    faq_plan = next(item for item in retrieval_index_plan.corpora if item.corpus == "faq")
    assert faq_plan.row_source_strategy == "host_python_fetch"
    assert faq_plan.row_source_module == "models.faq"
    assert faq_plan.row_source_callable == "get_all_faq"


def test_planner_prefers_host_python_fetch_for_db_backed_discovery_image_sources():
    retrieval_index_plan = planner_module._build_retrieval_index_plan(
        site_id="bilyeo",
        rag_sources=RagSources(
            discovery_image=[
                RagSourceRecord(
                    path="backend/models/product.py",
                    kind="code_file",
                    corpus="discovery_image",
                    reason="db-backed product model",
                    details={
                        "image_field": "image_url",
                        "source_surface": "db_table",
                        "loader_candidates": ["public_url_fetch", "bucket_list_and_fetch"],
                        "row_source_strategy": "host_python_fetch",
                        "row_source_module": "models.product",
                        "row_source_callable": "get_all_products",
                    },
                )
            ]
        ),
        run_id="runtime",
        product_search_endpoint="/api/products",
    )

    discovery_plan = next(item for item in retrieval_index_plan.corpora if item.corpus == "discovery_image")
    assert discovery_plan.row_source_strategy == "host_python_fetch"
    assert discovery_plan.row_source_module == "models.product"
    assert discovery_plan.row_source_callable == "get_all_products"
    assert discovery_plan.row_source_endpoint is None


def test_planner_builds_discovery_image_enrichment_contract_from_analysis_hints():
    retrieval_index_plan = planner_module._build_retrieval_index_plan(
        site_id="bilyeo",
        rag_sources=RagSources(
            discovery_image=[
                RagSourceRecord(
                    path="backend/models/product.py",
                    kind="code_file",
                    corpus="discovery_image",
                    reason="db-backed product model",
                    details={
                        "image_field": "image_url",
                        "row_source_strategy": "host_python_fetch",
                        "row_source_module": "models.product",
                        "row_source_callable": "get_all_products",
                        "text_field_candidates": ["name", "brand", "category"],
                        "payload_field_candidates": ["product_id", "name", "brand", "category"],
                        "nested_text_paths": ["product_info.ingredients"],
                        "auxiliary_relation_hints": [
                            {
                                "table_name": "product_info",
                                "key_field": "product_id",
                                "merge_as": "product_info",
                                "text_fields": ["ingredients", "review"],
                            }
                        ],
                    },
                )
            ]
        ),
        run_id="runtime",
        product_search_endpoint="/api/products",
    )

    discovery_plan = next(item for item in retrieval_index_plan.corpora if item.corpus == "discovery_image")
    assert discovery_plan.dense_image_field == "image_url"
    assert "product_info.ingredients" in discovery_plan.sparse_text_paths
    assert "product_info.review" in discovery_plan.sparse_text_paths
    assert "product_info" in discovery_plan.payload_paths
    assert discovery_plan.row_enrichment_strategy == "host_python_wrapper"


def test_planner_keeps_static_source_scan_for_materialized_faq_files():
    retrieval_index_plan = planner_module._build_retrieval_index_plan(
        site_id="demo",
        rag_sources=RagSources(
            faq=[
                RagSourceRecord(
                    path="scripts/faq_seed.json",
                    kind="json_file",
                    corpus="faq",
                    reason="materialized faq export",
                )
            ]
        ),
        run_id="runtime",
        product_search_endpoint="/api/products",
    )

    faq_plan = next(item for item in retrieval_index_plan.corpora if item.corpus == "faq")
    assert faq_plan.row_source_strategy == "static_source_scan"
    assert faq_plan.row_source_module is None
    assert faq_plan.row_source_callable is None
