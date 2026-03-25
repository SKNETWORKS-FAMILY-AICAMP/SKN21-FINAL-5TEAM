import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.compile.strategies.backend.django import compile_django_backend_bundle
from chatbot.src.onboarding_v2.models.planning import HostBackendPlan
from chatbot.src.onboarding_v2.planning import build_planning_bundle


def test_compiler_builds_complete_food_program():
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    plan = planning_bundle.integration_plan
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "food",
    )

    backend_bundle = program.host_program.backend_wiring_bundles[0]
    assert backend_bundle.target_paths == [
        "backend/foodshop/urls.py",
        "backend/orders/views.py",
    ]
    assert backend_bundle.supporting_files[0].path == "backend/chat_auth.py"
    route_operation = next(
        operation for operation in backend_bundle.operations if operation.path == "backend/foodshop/urls.py"
    )
    assert 'path("api/chat/auth-token", chat_auth_token)' in route_operation.new
    order_action_operation = next(
        operation for operation in backend_bundle.operations if operation.path == "backend/orders/views.py"
    )
    assert "new_option_id" in order_action_operation.new
    assert "selected_product" in order_action_operation.new
    assert "if selected_product is not None:" in order_action_operation.new
    assert '"new_option_id 값을 보내주세요."' not in order_action_operation.new
    assert "Order.Status.EXCHANGE_REQUESTED" in order_action_operation.new
    assert program.host_program.frontend_mount_bundles[0].target_path == "frontend/src/App.js"
    assert program.host_program.frontend_api_bundles[0].target_path == "frontend/src/api/api.js"
    assert program.chatbot_program.bridge_bundles[0].target_paths == ["src/adapters/setup.py"]
    mount_operation = program.host_program.frontend_mount_bundles[0].operations[0]
    assert 'process.env.REACT_APP_CHATBOT_SERVER_BASE_URL || "http://127.0.0.1:8100"' in mount_operation.new
    assert 'chatbotServerBaseUrl: "http://localhost:8100"' not in mount_operation.new
    assert {
        bundle.path for bundle in program.chatbot_program.supporting_artifact_bundles
    } >= {
        "src/adapters/generated/food/__init__.py",
        "src/adapters/generated/food/client.py",
        "src/adapters/generated/food/auth.py",
        "src/adapters/generated/food/mappers.py",
        "src/adapters/generated/food/adapter.py",
    }
    assert program.chatbot_program.compile_preflight is not None
    assert program.chatbot_program.compile_preflight.artifact_type == "compile-preflight"
    assert program.chatbot_program.compile_preflight.check_name == "chatbot_runtime_import"
    assert program.execution_metadata["planning_notes"] == plan.planning_notes.model_dump(mode="json")
    assert program.execution_metadata["target_bindings"]
    assert program.execution_metadata["repair_hints"] == [
        item.model_dump(mode="json") for item in planning_bundle.repair_hints
    ]


def test_compiler_tolerates_multiline_models_import_and_next_def_boundary(tmp_path: Path):
    route_path = tmp_path / "backend" / "project" / "urls.py"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
        encoding="utf-8",
    )
    order_views_path = tmp_path / "backend" / "orders" / "views.py"
    order_views_path.parent.mkdir(parents=True, exist_ok=True)
    order_views_path.write_text(
        "from django.shortcuts import get_object_or_404\n"
        "from rest_framework import status\n"
        "from rest_framework.response import Response\n\n"
        "from .models import (\n"
        "    Order,\n"
        ")\n\n"
        "def add_cors_headers(response):\n"
        "    return response\n\n"
        "def serialize_order(order, request):\n"
        "    return {}\n\n"
        "def _handle_exchange(order, request):\n"
        "    if order.payment_status != Order.PaymentStatus.PAID:\n"
        "        return add_cors_headers(\n"
        "            Response(\n"
        '                {"detail": "결제된 주문만 교환을 요청할 수 있습니다."},\n'
        "                status=status.HTTP_400_BAD_REQUEST,\n"
        "            )\n"
        "        )\n"
        "    order.status = Order.Status.EXCHANGE_REQUESTED\n"
        '    order.save(update_fields=["status"])\n\n'
        "    return add_cors_headers(\n"
        "        Response(\n"
        "            {\n"
        '                "message": "교환이 접수되었습니다.",\n'
        '                "order": serialize_order(order, request),\n'
        "            }\n"
        "        )\n"
        "    )\n\n"
        "def _handle_tracking(order, request):\n"
        "    return add_cors_headers(Response({\"message\": \"tracking\"}))\n",
        encoding="utf-8",
    )

    bundle = compile_django_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/project/urls.py",
            import_target="backend/project/urls.py",
            order_action_target="backend/orders/views.py",
            auth_handler_source="backend/users/views.py",
            generated_handler_path=None,
            site_id="food",
        ),
    )

    order_action_operation = next(
        operation for operation in bundle.operations if operation.path == "backend/orders/views.py"
    )
    assert "from products.models import Product\n" in order_action_operation.new
    assert "def _handle_tracking(order, request):\n" in order_action_operation.new
    assert "if selected_product is not None:" in order_action_operation.new
    assert '"new_option_id 값을 보내주세요."' not in order_action_operation.new
