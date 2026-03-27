import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models import (
    AnalysisSnapshot,
    ApplyResult,
    ArtifactEnvelope,
    ArtifactRef,
    AnalysisBundle,
    CandidateSet,
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    BackendSeams,
    ChatbotBridgeBundle,
    ChatbotBridgePlan,
    ChatbotEditProgram,
    DomainIntegration,
    EditProgram,
    FrameworkProfile,
    FailureBundle,
    FrontendSeams,
    HostBackendPlan,
    HostEditProgram,
    HostFrontendPlan,
    IntegrationPlan,
    IntegrationStrategy,
    PlanningBundle,
    PlanningCoverageReport,
    RagCorpusPlan,
    RagSourceRecord,
    RagSources,
    PathCandidate,
    ReplayResult,
    RepairDecision,
    ResolvedAuthContract,
    ResolvedOrderActionContract,
    ResolvedRequestFieldContract,
    ResolvedResponseContract,
    RetrievalIndexPlan,
    RetrievalPlan,
    RepoProfile,
    StrategyCandidate,
    TargetBinding,
    RunSummaryView,
    ValidationBundle,
    WorkspaceProfile,
)


def test_model_contracts_round_trip():
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="food",
            source_root="/tmp/food",
            backend_framework="django",
            frontend_framework="react",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(
            auth_source_candidates=[PathCandidate(path="backend/users/views.py", reason="auth")],
        ),
        frontend_seams=FrontendSeams(
            app_shell_candidates=[PathCandidate(path="frontend/src/App.js", reason="shell")],
        ),
        domain_integration=DomainIntegration(),
        rag_sources=RagSources(
            faq=[RagSourceRecord(path="backend/faq.json", kind="json_file", corpus="faq", reason="faq seed")],
        ),
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/foodshop/urls.py",
            import_target="backend/foodshop/urls.py",
            login_endpoint="/api/users/login/",
            auth_handler_source="backend/users/views.py",
            generated_handler_path="backend/chat_auth.py",
            site_id="food",
            capability_profile="order_cs_plus_retrieval",
            enabled_retrieval_corpora=["faq"],
            widget_features={"image_upload": False},
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
            capability_profile="order_cs_plus_retrieval",
            enabled_retrieval_corpora=["faq"],
            widget_features={"image_upload": False},
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="food",
            adapter_package="src/adapters/generated/food",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_FOOD_API_URL",
            auth_validation_endpoint="/api/users/me/",
            current_user_endpoint="/api/users/me/",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
            auth_transport="session_cookie",
            session_cookie_name="session_token",
            response_contract=ResolvedResponseContract(
                user_profile="wrapped_user",
                product_profile="list_items_named_price",
                order_profile="rest_detail_wrapped_order",
                delivery_profile="rest_detail_wrapped_order",
                order_status_profile="english_tokens",
                delivery_status_profile="english_tokens",
                order_identifier_mode="direct_order_id",
            ),
            order_action_contract=ResolvedOrderActionContract(
                submission_mode="single_endpoint_json_body",
                supported_actions=[
                    "list_orders",
                    "get_order_status",
                    "cancel",
                    "refund",
                    "exchange",
                ],
                request_fields=ResolvedRequestFieldContract(
                    action="action",
                    reason="reason",
                    new_option_id="new_option_id",
                ),
                reason_transport="json_body",
                new_option_transport="json_body",
                result_profile="accepted_message",
            ),
        ),
        retrieval_index_plan=RetrievalIndexPlan(
            site_id="food",
            site_slug="food",
            corpora=[
                RagCorpusPlan(
                    corpus="faq",
                    enabled=True,
                    chunking_strategy="qa_level",
                    collection_alias="site_food__faq",
                    build_collection="site_food__faq__run_food-run-v2",
                    sources=["backend/faq.json"],
                    smoke_queries=["환불 규정"],
                    minimum_expected_documents=1,
                )
            ],
        ),
        capability_upgrade={
            "capability_profile": "order_cs_plus_retrieval",
            "enabled_retrieval_corpora": ["faq"],
            "widget_features": {"image_upload": False},
        },
    )
    envelope = ArtifactEnvelope(
        artifact_id="analysis:snapshot:v0001",
        artifact_type="snapshot",
        stage="analysis",
        version=1,
        created_at="2026-03-23T00:00:00+00:00",
        producer="test",
        payload=snapshot.model_dump(mode="json"),
    )
    summary = RunSummaryView(
        run_id="food-run-v2",
        site="food",
        status="pending",
        latest_rewind_to="validation",
        repair_attempt_count=2,
        stopped_for_review=False,
        retrieval_status={
            "faq": {"status": "completed", "enabled": True},
            "policy": {"status": "skipped", "enabled": False},
            "discovery_image": {"status": "skipped", "enabled": False},
        },
        final_capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["faq"],
    )
    prep = BackendRuntimePrepResult(framework="django", passed=True)
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root="/tmp/food/backend",
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
        environment={"DJANGO_SETTINGS_MODULE": "foodshop.settings"},
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    apply_result = ApplyResult(
        workspace_path="/tmp/runtime/food/workspace",
        host_workspace_path="/tmp/runtime/food/workspace/host",
        chatbot_workspace_path="/tmp/runtime/food/workspace/chatbot",
        host_source_snapshot_path="/tmp/runtime/food/source-snapshot/host",
        chatbot_source_snapshot_path="/tmp/runtime/food/source-snapshot/chatbot",
        passed=True,
        host_applied_files=["frontend/src/App.js"],
        chatbot_applied_files=["src/adapters/setup.py"],
    )
    replay_result = ReplayResult(
        replay_workspace_path="/tmp/runtime/food/export-replay-workspace",
        host_replay_workspace_path="/tmp/runtime/food/export-replay-workspace/host",
        chatbot_replay_workspace_path="/tmp/runtime/food/export-replay-workspace/chatbot",
        host_patch_path="/tmp/generated/food/host-approved.patch",
        chatbot_patch_path="/tmp/generated/food/chatbot-approved.patch",
        host_baseline_root="/tmp/runtime/food/source-snapshot/host",
        chatbot_baseline_root="/tmp/runtime/food/source-snapshot/chatbot",
        passed=True,
        host_allowed_targets=["frontend/src/App.js"],
        chatbot_allowed_targets=["src/adapters/setup.py"],
    )

    assert envelope.payload["repo_profile"]["site"] == "food"
    assert snapshot.rag_sources.faq[0].path == "backend/faq.json"
    assert plan.host_backend.generated_handler_path == "backend/chat_auth.py"
    assert plan.host_backend.order_lookup_target == "backend/orders/views.py"
    assert plan.host_backend.order_action_target == "backend/orders/views.py"
    assert plan.host_backend.exchange_strategy == "augment_existing_order_action_endpoint"
    assert plan.host_backend.order_action_request_field == "action"
    assert plan.host_backend.order_action_reason_field == "reason"
    assert plan.host_backend.order_action_new_option_field == "new_option_id"
    assert plan.host_backend.order_action_response_serializer == "serialize_order"
    assert plan.host_backend.exchange_status_transition == "EXCHANGE_REQUESTED"
    assert plan.host_backend.supported_order_tools == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]
    assert plan.chatbot_bridge.site_key == "food"
    assert plan.chatbot_bridge.supported_tools == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]
    assert plan.chatbot_bridge.auth_transport == "session_cookie"
    assert plan.chatbot_bridge.session_cookie_name == "session_token"
    assert plan.chatbot_bridge.csrf_cookie_name is None
    assert plan.chatbot_bridge.csrf_header_name is None
    assert plan.chatbot_bridge.auth_contract.transport == "session_cookie"
    assert plan.chatbot_bridge.auth_contract.session_cookie_name == "session_token"
    assert plan.chatbot_bridge.response_contract.order_profile == "rest_detail_wrapped_order"
    assert plan.chatbot_bridge.order_action_contract.submission_mode == "single_endpoint_json_body"
    assert plan.chatbot_bridge.response_mapping_profile == "rest_detail_wrapped_order"
    assert plan.chatbot_bridge.request_field_mappings["new_option_id"] == "new_option_id"
    assert plan.host_frontend.chatbot_server_base_url_expression == ""
    assert plan.host_frontend.enabled_retrieval_corpora == ["faq"]
    assert plan.host_backend.capability_profile == "order_cs_plus_retrieval"
    assert plan.retrieval_index_plan.corpora[0].collection_alias == "site_food__faq"
    assert plan.capability_upgrade["enabled_retrieval_corpora"] == ["faq"]
    program = EditProgram(
        host_program=HostEditProgram(),
        chatbot_program=ChatbotEditProgram(
            bridge_bundles=[
                ChatbotBridgeBundle(
                    bundle_id="chatbot:generated-adapter",
                    target_paths=["src/adapters/setup.py"],
                )
            ]
        ),
    )
    assert program.model_dump()["execution_metadata"] == {}
    assert program.chatbot_program.bridge_bundles[0].target_paths == ["src/adapters/setup.py"]
    assert ValidationBundle(passed=True).passed is True
    assert ArtifactRef(stage="analysis", artifact_type="snapshot", version=1, path="v0001.json", content_hash="x").path == "v0001.json"
    assert summary.status == "pending"
    assert summary.retrieval_status["faq"]["status"] == "completed"
    assert summary.final_capability_profile == "order_cs_plus_retrieval"
    assert summary.enabled_retrieval_corpora == ["faq"]
    assert prep.framework == "django"
    assert runtime_plan.readiness_url.endswith("/api/chat/auth-token")
    assert runtime_state.passed is True
    assert apply_result.host_source_snapshot_path.endswith("source-snapshot/host")
    assert replay_result.host_allowed_targets == ["frontend/src/App.js"]
    assert summary.latest_rewind_to == "validation"
    assert summary.repair_attempt_count == 2


def test_chatbot_bridge_plan_prefers_nested_auth_contract_and_mirrors_legacy_fields():
    plan = ChatbotBridgePlan.model_validate(
        {
            "site_key": "food",
            "adapter_package": "src/adapters/generated/food",
            "setup_target": "src/adapters/setup.py",
            "host_base_url_env_var": "GENERATED_FOOD_API_URL",
            "auth_validation_endpoint": "/api/users/me/",
            "current_user_endpoint": "/api/users/me/",
            "product_search_endpoint": "/api/products/",
            "order_list_endpoint": "/api/orders/",
            "order_detail_endpoint": "/api/orders/{order_id}/",
            "order_action_endpoint": "/api/orders/{order_id}/actions/",
            "auth_contract": {
                "transport": "session_cookie",
                "session_cookie_name": "session_token",
            },
            "auth_transport": "bearer_token",
            "session_cookie_name": "ignored_cookie",
            "csrf_cookie_name": "ignored_csrf",
            "csrf_header_name": "Ignored-CSRF",
        }
    )

    assert isinstance(plan.auth_contract, ResolvedAuthContract)
    assert plan.auth_contract.transport == "session_cookie"
    assert plan.auth_contract.session_cookie_name == "session_token"
    assert plan.auth_transport == "session_cookie"
    assert plan.session_cookie_name == "session_token"
    assert plan.csrf_cookie_name is None
    assert plan.csrf_header_name is None

    dumped = plan.model_dump(mode="json")

    assert dumped["auth_contract"]["transport"] == "session_cookie"
    assert dumped["auth_transport"] == "session_cookie"
    assert dumped["session_cookie_name"] == "session_token"


def test_chatbot_bridge_plan_accepts_legacy_auth_fields_without_nested_contract():
    plan = ChatbotBridgePlan.model_validate(
        {
            "site_key": "bilyeo",
            "adapter_package": "src/adapters/generated/bilyeo",
            "setup_target": "src/adapters/setup.py",
            "host_base_url_env_var": "GENERATED_BILYEO_API_URL",
            "auth_validation_endpoint": "/api/chat/auth-token",
            "current_user_endpoint": "/api/chat/auth-token",
            "product_search_endpoint": "/api/products",
            "order_list_endpoint": "/api/orders/all",
            "order_detail_endpoint": "/api/orders/{order_id}",
            "order_action_endpoint": "/api/orders/{order_id}/exchange",
            "auth_transport": "bearer_token",
        }
    )

    assert plan.auth_contract.transport == "bearer_token"
    assert plan.auth_contract.session_cookie_name is None
    assert plan.auth_transport == "bearer_token"


def test_chatbot_bridge_plan_prefers_nested_response_and_order_action_contracts():
    plan = ChatbotBridgePlan.model_validate(
        {
            "site_key": "food",
            "adapter_package": "src/adapters/generated/food",
            "setup_target": "src/adapters/setup.py",
            "host_base_url_env_var": "GENERATED_FOOD_API_URL",
            "auth_validation_endpoint": "/api/users/me/",
            "current_user_endpoint": "/api/users/me/",
            "product_search_endpoint": "/api/products/",
            "order_list_endpoint": "/api/orders/",
            "order_detail_endpoint": "/api/orders/{order_id}/",
            "order_action_endpoint": "/api/orders/{order_id}/actions/",
            "response_contract": {
                "user_profile": "wrapped_user",
                "product_profile": "list_items_named_price",
                "order_profile": "rest_detail_wrapped_order",
                "delivery_profile": "rest_detail_wrapped_order",
                "order_status_profile": "english_tokens",
                "delivery_status_profile": "english_tokens",
                "order_identifier_mode": "direct_order_id",
            },
            "order_action_contract": {
                "submission_mode": "single_endpoint_json_body",
                "supported_actions": ["list_orders", "get_order_status", "cancel"],
                "request_fields": {
                    "action": "action_type",
                    "reason": "reason_text",
                    "new_option_id": "variant_id",
                },
                "reason_transport": "json_body",
                "new_option_transport": "json_body",
                "result_profile": "accepted_message",
            },
            "response_mapping_profile": "legacy_profile",
            "request_field_mappings": {
                "action": "legacy_action",
                "reason": "legacy_reason",
                "new_option_id": "legacy_option",
            },
            "supported_tools": ["legacy_tool"],
        }
    )

    assert plan.response_contract.order_profile == "rest_detail_wrapped_order"
    assert plan.order_action_contract.submission_mode == "single_endpoint_json_body"
    assert plan.order_action_contract.request_fields.action == "action_type"
    assert plan.response_mapping_profile == "rest_detail_wrapped_order"
    assert plan.request_field_mappings == {
        "action": "action_type",
        "reason": "reason_text",
        "new_option_id": "variant_id",
    }
    assert plan.supported_tools == ["list_orders", "get_order_status", "cancel"]


def test_repair_model_contracts_round_trip():
    artifact_ref = ArtifactRef(
        stage="validation",
        artifact_type="validation-bundle",
        version=1,
        path="v0001.json",
        content_hash="abc123",
    )
    failure = FailureBundle(
        failed_stage="validation",
        failure_signature="smoke_step_order_api_returned_500",
        failure_summary="step order-api returned 500",
        trigger_event_id="evt-123",
        related_artifacts=[artifact_ref],
        related_files=["backend/orders/views.py"],
        related_file_samples=[
            {
                "path": "backend/orders/views.py",
                "content": "def list_orders(request):\n    return None\n",
            }
        ],
        input_artifact_versions={"validation": 1},
        attempt_number=2,
        repeat_count=1,
    )
    decision = RepairDecision(
        failure_signature=failure.failure_signature,
        diagnosis="order api runtime failure requires validation rerun",
        rewind_to="validation",
        preserve_artifacts=["analysis", "planning", "compile", "apply", "export"],
        required_rechecks=["smoke"],
        additional_discovery=[],
        artifact_overrides={},
        stop=False,
    )

    assert failure.failed_stage == "validation"
    assert failure.related_file_samples[0]["path"] == "backend/orders/views.py"
    assert decision.rewind_to == "validation"
    assert decision.stop_reason is None


def test_analysis_and_planning_bundles_accept_retrieval_contracts():
    snapshot = AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="bilyeo",
            source_root="/tmp/bilyeo",
            backend_framework="flask",
            frontend_framework="vue",
            auth_style="session_cookie",
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(),
        rag_sources=RagSources(
            policy=[
                RagSourceRecord(
                    path="scripts/faq_crawling.py",
                    kind="crawl_script",
                    corpus="policy",
                    reason="policy crawler",
                )
            ],
            discovery_image=[
                RagSourceRecord(
                    path="scripts/product_crawling.py",
                    kind="crawl_script",
                    corpus="discovery_image",
                    reason="product image crawler",
                )
            ],
        ),
    )
    analysis_bundle = AnalysisBundle(
        workspace_profile=WorkspaceProfile(root="/tmp/bilyeo"),
        framework_profile=FrameworkProfile(
            backend_framework="flask",
            frontend_framework="vue",
            auth_style="session_cookie",
        ),
        retrieval_plan=RetrievalPlan(),
        candidate_set=CandidateSet(),
        snapshot=snapshot,
        rag_sources=snapshot.rag_sources,
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/routes/auth.py",
            site_id="bilyeo",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="bilyeo",
            adapter_package="src/adapters/generated/bilyeo",
            setup_target="src/adapters/generated/setup.py",
            host_base_url_env_var="GENERATED_BILYEO_API_URL",
            auth_validation_endpoint="/api/auth/me",
            current_user_endpoint="/api/auth/me",
            product_search_endpoint="/api/products",
            order_list_endpoint="/api/orders/all",
            order_detail_endpoint="/api/orders/{order_id}",
            order_action_endpoint="/api/orders/{order_id}/refund",
        ),
    )
    planning_bundle = PlanningBundle(
        coverage_report=PlanningCoverageReport(covered=True),
        strategy_candidates=[StrategyCandidate(candidate_id="b1", layer="backend", strategy="flask_app_register_blueprint", summary="ok")],
        integration_strategy=IntegrationStrategy(
            backend_strategy="flask_app_register_blueprint",
            frontend_mount_strategy="react_app_shell_outside_routes",
            frontend_api_strategy="react_api_client_augment_existing",
        ),
        integration_plan=plan,
        retrieval_index_plan=RetrievalIndexPlan(
            site_id="bilyeo",
            site_slug="bilyeo",
            corpora=[
                RagCorpusPlan(
                    corpus="policy",
                    enabled=True,
                    chunking_strategy="heading_sections",
                    collection_alias="site_bilyeo__policy",
                    build_collection="site_bilyeo__policy__run_bilyeo-run-v2",
                    sources=["scripts/faq_crawling.py"],
                    smoke_queries=["반품 규정"],
                    minimum_expected_documents=1,
                )
            ],
        ),
        capability_upgrade={
            "capability_profile": "order_cs_plus_retrieval",
            "enabled_retrieval_corpora": ["policy"],
            "widget_features": {"image_upload": False},
        },
    )

    assert analysis_bundle.rag_sources.discovery_image[0].corpus == "discovery_image"
    assert planning_bundle.retrieval_index_plan.corpora[0].collection_alias == "site_bilyeo__policy"
