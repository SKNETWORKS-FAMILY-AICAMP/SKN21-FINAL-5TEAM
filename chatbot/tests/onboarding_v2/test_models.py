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
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    BackendSeams,
    ChatbotBridgeBundle,
    ChatbotBridgePlan,
    ChatbotEditProgram,
    DomainIntegration,
    EditProgram,
    FailureBundle,
    FrontendSeams,
    HostBackendPlan,
    HostEditProgram,
    HostFrontendPlan,
    IntegrationPlan,
    PathCandidate,
    ReplayResult,
    RepairDecision,
    RepoProfile,
    RunSummaryView,
    ValidationBundle,
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
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/foodshop/urls.py",
            import_target="backend/foodshop/urls.py",
            auth_handler_source="backend/users/views.py",
            generated_handler_path="backend/chat_auth.py",
            site_id="food",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
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
        ),
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
    assert plan.chatbot_bridge.auth_transport == "session_token_cookie"
    assert plan.chatbot_bridge.response_mapping_profile == "site_a"
    assert plan.chatbot_bridge.request_field_mappings["new_option_id"] == "new_option_id"
    assert plan.host_frontend.chatbot_server_base_url_expression == ""
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
    assert prep.framework == "django"
    assert runtime_plan.readiness_url.endswith("/api/chat/auth-token")
    assert runtime_state.passed is True
    assert apply_result.host_source_snapshot_path.endswith("source-snapshot/host")
    assert replay_result.host_allowed_targets == ["frontend/src/App.js"]
    assert summary.latest_rewind_to == "validation"
    assert summary.repair_attempt_count == 2


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
