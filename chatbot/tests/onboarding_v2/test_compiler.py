import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.compile.preflight import run_flask_host_import_smoke
from chatbot.src.onboarding_v2.compile.strategies.backend.django import compile_django_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.backend.flask import compile_flask_backend_bundle
from chatbot.src.onboarding_v2.models.planning import HostBackendPlan
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding_v2.planning.planner import _choose_generated_handler_path


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
    generated_client = next(
        bundle.content
        for bundle in program.chatbot_program.supporting_artifact_bundles
        if bundle.path == "src/adapters/generated/food/client.py"
    )
    assert "SiteAClient" not in generated_client
    assert '"/api/orders/{order_id}/actions/"' in generated_client
    assert '"/api/users/me/"' in generated_client
    assert program.chatbot_program.compile_preflight is not None
    assert program.chatbot_program.compile_preflight.artifact_type == "compile-preflight"
    assert program.chatbot_program.compile_preflight.check_name == "chatbot_runtime_import"
    assert set(program.chatbot_program.compile_preflight.scan_paths) == {
        "src/adapters/setup.py",
        "src/adapters/generated/food/__init__.py",
        "src/adapters/generated/food/client.py",
        "src/adapters/generated/food/auth.py",
        "src/adapters/generated/food/mappers.py",
        "src/adapters/generated/food/adapter.py",
    }
    assert program.execution_metadata["planning_notes"] == plan.planning_notes.model_dump(mode="json")
    assert program.execution_metadata["target_bindings"]
    assert program.execution_metadata["repair_hints"] == [
        item.model_dump(mode="json") for item in planning_bundle.repair_hints
    ]


def test_compiler_uses_chat_auth_bridge_for_bilyeo_bearer_validation():
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "bilyeo",
    )

    generated_client = next(
        bundle.content
        for bundle in program.chatbot_program.supporting_artifact_bundles
        if bundle.path == "src/adapters/generated/bilyeo/client.py"
    )
    generated_auth = next(
        bundle.content
        for bundle in program.chatbot_program.supporting_artifact_bundles
        if bundle.path == "src/adapters/generated/bilyeo/auth.py"
    )

    assert 'return await self._request("GET", "/api/chat/auth-token", headers=headers)' in generated_client
    assert 'headers["Authorization"] = f"Bearer {ctx.accessToken}"' in generated_auth
    assert 'cookie_map["session_token"] = ctx.accessToken' not in generated_auth
    assert '"주문완료": OrderStatus.PAID' in generated_adapter
    assert '"배송준비중": OrderStatus.PREPARING' in generated_adapter
    assert '"배송완료": OrderStatus.DELIVERED' in generated_adapter


def test_compiler_registers_generated_adapter_in_setup_bundle():
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "bilyeo",
    )

    setup_operation = program.chatbot_program.bridge_bundles[0].operations[0]

    assert "generated_bilyeo_adapter = GeneratedBilyeoAdapter" in setup_operation.new
    assert "AdapterRegistry.register_many([" in setup_operation.new
    assert "generated_bilyeo_adapter," in setup_operation.new


def test_compiler_uses_site_specific_generated_host_url_fallback():
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "bilyeo",
    )

    setup_operation = program.chatbot_program.bridge_bundles[0].operations[0]

    assert 'os.environ.get("GENERATED_BILYEO_API_URL")' in setup_operation.new
    assert 'os.environ.get("BILYEO_API_URL")' in setup_operation.new
    assert 'locals().get("bilyeo_url", "")' in setup_operation.new
    assert 'os.environ.get("GENERATED_BILYEO_API_URL", food_url)' not in setup_operation.new


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
            login_endpoint="/api/users/login/",
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


def test_planner_uses_backend_chat_auth_path_for_flask():
    assert _choose_generated_handler_path("flask") == "backend/chat_auth.py"


def test_compile_flask_backend_bundle_inserts_factory_blueprint_registration(tmp_path: Path):
    app_path = tmp_path / "backend" / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(
        "from flask import Flask\n"
        "from existing import existing_blueprint\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        '    app.config["TESTING"] = True\n'
        '    app.register_blueprint(existing_blueprint, url_prefix="/existing")\n'
        "    return app\n",
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/users.py",
            generated_handler_path="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="demo",
        ),
    )

    assert bundle.supporting_files[0].path == "backend/chat_auth.py"
    assert '@chat_auth_blueprint.route("/auth-token", methods=["GET", "POST"])' in bundle.supporting_files[0].content
    assert "/api/chat/auth-token" not in bundle.supporting_files[0].content
    updated = bundle.operations[0].new
    assert "from chat_auth import chat_auth_blueprint\n" in updated
    assert 'app.register_blueprint(chat_auth_blueprint, url_prefix="/api/chat")\n' in updated
    assert updated.index('app.register_blueprint(existing_blueprint, url_prefix="/existing")') < updated.index(
        'app.register_blueprint(chat_auth_blueprint, url_prefix="/api/chat")'
    )
    assert updated.index('app.register_blueprint(chat_auth_blueprint, url_prefix="/api/chat")') < updated.index(
        "    return app"
    )


def test_compile_django_backend_bundle_resolves_helper_source_from_users_views(tmp_path: Path):
    route_path = tmp_path / "backend" / "project" / "urls.py"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
        encoding="utf-8",
    )
    orders_views_path = tmp_path / "backend" / "orders" / "views.py"
    orders_views_path.parent.mkdir(parents=True, exist_ok=True)
    orders_views_path.write_text(
        "from rest_framework.response import Response\n\n"
        "def serialize_order(order, request):\n"
        "    return {}\n\n"
        "def _handle_exchange(order, request):\n"
        "    return Response({})\n",
        encoding="utf-8",
    )
    users_views_path = tmp_path / "backend" / "users" / "views.py"
    users_views_path.parent.mkdir(parents=True, exist_ok=True)
    users_views_path.write_text(
        "def _build_user_payload(user):\n"
        "    return {'id': user.id}\n\n"
        "def _find_active_session(request):\n"
        "    return None\n",
        encoding="utf-8",
    )

    bundle = compile_django_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/project/urls.py",
            import_target="backend/project/urls.py",
            login_endpoint="/api/users/login/",
            order_action_target="",
            auth_handler_source="backend/orders/views.py",
            generated_handler_path="backend/chat_auth.py",
            site_id="food",
        ),
    )

    generated = bundle.supporting_files[0].content

    assert "from users.views import _build_user_payload, _find_active_session" in generated
    assert "from orders.views import _build_user_payload, _find_active_session" not in generated


def test_compile_django_backend_bundle_fails_fast_when_helper_source_missing(tmp_path: Path):
    route_path = tmp_path / "backend" / "project" / "urls.py"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(
        "from django.urls import path\n\nurlpatterns = []\n",
        encoding="utf-8",
    )
    orders_views_path = tmp_path / "backend" / "orders" / "views.py"
    orders_views_path.parent.mkdir(parents=True, exist_ok=True)
    orders_views_path.write_text(
        "from rest_framework.response import Response\n\n"
        "def serialize_order(order, request):\n"
        "    return {}\n\n"
        "def _handle_exchange(order, request):\n"
        "    return Response({})\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="django_chat_auth_helper_source_missing_helpers"):
        compile_django_backend_bundle(
            source_root=tmp_path,
            plan=HostBackendPlan(
                strategy="django_project_urlconf_import_view",
                route_target="backend/project/urls.py",
                import_target="backend/project/urls.py",
                login_endpoint="/api/users/login/",
                order_action_target="",
                auth_handler_source="backend/orders/views.py",
                generated_handler_path="backend/chat_auth.py",
                site_id="food",
            ),
        )


def test_compile_flask_backend_bundle_generates_validation_aware_bridge_payload(tmp_path: Path):
    app_path = tmp_path / "backend" / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(
        "from flask import Flask\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    return app\n",
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/routes/auth.py",
            generated_handler_path="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
    )

    generated = bundle.supporting_files[0].content

    assert "ONBOARDING_VALIDATION" in generated
    assert '"authenticated": True' in generated or '"authenticated": true' in generated
    assert '"site_id": "bilyeo"' in generated
    assert 'f"validation-bilyeo"' in generated or '"validation-bilyeo"' in generated
    assert '"id": "validation-user"' in generated


def test_compile_flask_backend_bundle_preserves_existing_chat_auth_contract(tmp_path: Path):
    app_path = tmp_path / "backend" / "app.py"
    chat_auth_path = tmp_path / "backend" / "chat_auth.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(
        "from flask import Flask\n"
        "from chat_auth import chat_auth_bp\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        '    app.register_blueprint(chat_auth_bp, url_prefix="/api")\n'
        "    return app\n",
        encoding="utf-8",
    )
    chat_auth_path.write_text(
        "from flask import Blueprint, jsonify, request, session\n"
        "from models.user import find_user_by_id\n\n"
        "chat_auth_bp = Blueprint('chat_auth', __name__)\n"
        '_SITE_ID = "site-b"\n\n'
        "def _parse_bearer_token(value):\n"
        "    return value or ''\n\n"
        "def resolve_authenticated_user_id():\n"
        "    return session.get('user_id')\n\n"
        "def get_authenticated_user():\n"
        "    user_id = resolve_authenticated_user_id()\n"
        "    return None if user_id is None else find_user_by_id(user_id)\n\n"
        "@chat_auth_bp.route('/chat/auth-token', methods=['POST'])\n"
        "def chat_auth_token():\n"
        "    return jsonify({'authenticated': False}), 401\n",
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/routes/auth.py",
            generated_handler_path="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
    )

    updated = bundle.operations[0].new
    handler_operation = next(
        operation for operation in bundle.operations if operation.path == "backend/chat_auth.py"
    )
    generated = handler_operation.new

    assert "from chat_auth import chat_auth_bp\n" in updated
    assert "from chat_auth import chat_auth_blueprint\n" not in updated
    assert updated.count('app.register_blueprint(chat_auth_bp, url_prefix="/api")') == 1
    assert 'app.register_blueprint(chat_auth_blueprint, url_prefix="/api/chat")' not in updated
    assert bundle.supporting_files == []
    assert "def resolve_authenticated_user_id():" in generated
    assert "def get_authenticated_user():" in generated
    assert "def _runtime_capability_payload():" in generated
    assert 'if os.environ.get("ONBOARDING_VALIDATION") == "1":' in generated
    assert "chat_auth_bp = Blueprint(" in generated
    assert '@chat_auth_bp.route("/chat/auth-token", methods=["GET", "POST"])' in generated
    assert "find_user_by_email" in generated
    assert "validation-bilyeo" not in generated


def test_compile_flask_backend_bundle_preserved_contract_boots_without_import_error(tmp_path: Path):
    backend_root = tmp_path / "backend"
    app_path = backend_root / "app.py"
    route_root = backend_root / "routes"
    route_root.mkdir(parents=True, exist_ok=True)
    app_path.parent.mkdir(parents=True, exist_ok=True)
    (route_root / "__init__.py").write_text("", encoding="utf-8")
    (route_root / "order.py").write_text(
        "from flask import Blueprint\n"
        "from chat_auth import get_authenticated_user\n\n"
        "order_bp = Blueprint('order', __name__)\n\n"
        "@order_bp.route('/orders')\n"
        "def orders():\n"
        "    return get_authenticated_user()\n",
        encoding="utf-8",
    )
    (backend_root / "models").mkdir(parents=True, exist_ok=True)
    (backend_root / "models" / "__init__.py").write_text("", encoding="utf-8")
    (backend_root / "models" / "user.py").write_text(
        "def find_user_by_id(user_id):\n"
        "    return {'user_id': user_id, 'email': 'test@example.com', 'name': 'Test'}\n",
        encoding="utf-8",
    )
    (backend_root / "chat_auth.py").write_text(
        "from flask import Blueprint, jsonify, request, session\n"
        "from models.user import find_user_by_id\n\n"
        "chat_auth_bp = Blueprint('chat_auth', __name__)\n\n"
        "def _parse_bearer_token(value):\n"
        "    return value or ''\n\n"
        "def resolve_authenticated_user_id():\n"
        "    return session.get('user_id')\n\n"
        "def get_authenticated_user():\n"
        "    user_id = resolve_authenticated_user_id()\n"
        "    return None if user_id is None else find_user_by_id(user_id)\n\n"
        "@chat_auth_bp.route('/chat/auth-token', methods=['POST'])\n"
        "def chat_auth_token():\n"
        "    user = get_authenticated_user()\n"
        "    return jsonify({'authenticated': user is not None})\n",
        encoding="utf-8",
    )
    app_path.write_text(
        "from flask import Flask\n"
        "from chat_auth import chat_auth_bp\n\n"
        "from routes.order import order_bp\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        '    app.register_blueprint(chat_auth_bp, url_prefix="/api")\n'
        '    app.register_blueprint(order_bp, url_prefix="/api")\n'
        "    return app\n",
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/routes/auth.py",
            generated_handler_path="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
    )

    for operation in bundle.operations:
        target_path = tmp_path / operation.path
        target_path.write_text(operation.new, encoding="utf-8")

    result = run_flask_host_import_smoke(
        host_workspace=tmp_path,
        entrypoint="app.py",
    )

    assert result.passed is True
    assert result.failure_code is None


def test_compile_flask_backend_bundle_preserved_contract_emits_numeric_validation_bearer_payload(
    tmp_path: Path,
    monkeypatch,
):
    backend_root = tmp_path / "backend"
    app_path = backend_root / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    (backend_root / "models").mkdir(parents=True, exist_ok=True)
    (backend_root / "models" / "__init__.py").write_text("", encoding="utf-8")
    (backend_root / "models" / "user.py").write_text(
        "def find_user_by_id(user_id):\n"
        "    return {'user_id': user_id, 'email': 'test@example.com', 'name': 'Kim Test'}\n\n"
        "def find_user_by_email(email):\n"
        "    if email == 'test@example.com':\n"
        "        return {'user_id': 7, 'email': email, 'name': 'Kim Test'}\n"
        "    return None\n",
        encoding="utf-8",
    )
    (backend_root / "chat_auth.py").write_text(
        "from flask import Blueprint, jsonify, request, session\n"
        "from models.user import find_user_by_id\n\n"
        "chat_auth_bp = Blueprint('chat_auth', __name__)\n"
        '_SITE_ID = "site-b"\n\n'
        "def _parse_bearer_token(value):\n"
        "    return value or ''\n\n"
        "def resolve_authenticated_user_id():\n"
        "    return session.get('user_id')\n\n"
        "def get_authenticated_user():\n"
        "    user_id = resolve_authenticated_user_id()\n"
        "    return None if user_id is None else find_user_by_id(user_id)\n\n"
        "@chat_auth_bp.route('/chat/auth-token', methods=['POST'])\n"
        "def chat_auth_token():\n"
        "    return jsonify({'authenticated': False}), 401\n",
        encoding="utf-8",
    )
    app_path.write_text(
        "from flask import Flask\n"
        "from chat_auth import chat_auth_bp\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        '    app.register_blueprint(chat_auth_bp, url_prefix="/api")\n'
        "    return app\n",
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/routes/auth.py",
            generated_handler_path="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
    )

    for operation in bundle.operations:
        (tmp_path / operation.path).write_text(operation.new, encoding="utf-8")

    monkeypatch.setenv("ONBOARDING_VALIDATION", "1")
    monkeypatch.setenv("ONBOARDING_CAPABILITY_PROFILE", "order_cs_plus_retrieval")
    monkeypatch.setenv("ONBOARDING_ENABLED_RETRIEVAL_CORPORA", '["policy","discovery_image"]')
    monkeypatch.setenv("ONBOARDING_WIDGET_FEATURES", '{"image_upload": true}')

    module_name = "compiled_flask_validation_bridge"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(backend_root))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = module.create_app()
        client = app.test_client()
        response = client.post("/api/chat/auth-token")
    finally:
        sys.path.pop(0)
        for module_key in [
            module_name,
            "app",
            "chat_auth",
            "models",
            "models.user",
        ]:
            sys.modules.pop(module_key, None)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["access_token"] == "7"
    assert payload["user"]["id"] == "7"
    assert payload["user"]["email"] == "test@example.com"
    assert payload["capability_profile"] == "order_cs_plus_retrieval"
    assert payload["enabled_retrieval_corpora"] == ["policy", "discovery_image"]
    assert payload["widget_features"]["image_upload"] is True


def test_run_flask_host_import_smoke_passes_for_preserved_contract(tmp_path: Path):
    backend_root = tmp_path / "backend"
    routes_root = backend_root / "routes"
    routes_root.mkdir(parents=True, exist_ok=True)
    (backend_root / "flask.py").write_text(
        "class Blueprint:\n"
        "    def __init__(self, name, import_name):\n"
        "        self.name = name\n"
        "        self.import_name = import_name\n"
        "        self._rules = []\n\n"
        "    def route(self, rule, methods=None):\n"
        "        def decorator(fn):\n"
        "            self._rules.append(rule)\n"
        "            return fn\n"
        "        return decorator\n\n"
        "class Flask:\n"
        "    def __init__(self, import_name):\n"
        "        self.import_name = import_name\n"
        "        self.blueprints = []\n\n"
        "    def register_blueprint(self, blueprint, url_prefix=None):\n"
        "        self.blueprints.append((blueprint, url_prefix))\n",
        encoding="utf-8",
    )
    (routes_root / "__init__.py").write_text("", encoding="utf-8")
    (routes_root / "order.py").write_text(
        "from flask import Blueprint\n"
        "from chat_auth import get_authenticated_user\n\n"
        "order_bp = Blueprint('order', __name__)\n\n"
        "@order_bp.route('/orders')\n"
        "def orders():\n"
        "    return get_authenticated_user()\n",
        encoding="utf-8",
    )
    (backend_root / "chat_auth.py").write_text(
        "from flask import Blueprint\n\n"
        "chat_auth_bp = Blueprint('chat_auth', __name__)\n\n"
        "def get_authenticated_user():\n"
        "    return {'id': 'validation-user'}\n\n"
        "@chat_auth_bp.route('/chat/auth-token', methods=['GET', 'POST'])\n"
        "def auth_token():\n"
        "    return {'authenticated': True}\n",
        encoding="utf-8",
    )
    (backend_root / "app.py").write_text(
        "from flask import Flask\n"
        "from chat_auth import chat_auth_bp\n"
        "from routes.order import order_bp\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    app.register_blueprint(chat_auth_bp, url_prefix='/api')\n"
        "    app.register_blueprint(order_bp, url_prefix='/api')\n"
        "    return app\n",
        encoding="utf-8",
    )

    result = run_flask_host_import_smoke(
        host_workspace=tmp_path,
        entrypoint="app.py",
    )

    assert result.passed is True
    assert result.failure_code is None
    assert result.details["framework"] == "flask"


def test_run_flask_host_import_smoke_reports_related_files_for_missing_chat_auth_helper(tmp_path: Path):
    backend_root = tmp_path / "backend"
    routes_root = backend_root / "routes"
    routes_root.mkdir(parents=True, exist_ok=True)
    (backend_root / "flask.py").write_text(
        "class Blueprint:\n"
        "    def __init__(self, name, import_name):\n"
        "        self.name = name\n"
        "        self.import_name = import_name\n\n"
        "    def route(self, rule, methods=None):\n"
        "        def decorator(fn):\n"
        "            return fn\n"
        "        return decorator\n\n"
        "class Flask:\n"
        "    def __init__(self, import_name):\n"
        "        self.import_name = import_name\n\n"
        "    def register_blueprint(self, blueprint, url_prefix=None):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (routes_root / "__init__.py").write_text("", encoding="utf-8")
    (routes_root / "order.py").write_text(
        "from flask import Blueprint\n"
        "from chat_auth import get_authenticated_user\n\n"
        "order_bp = Blueprint('order', __name__)\n",
        encoding="utf-8",
    )
    (backend_root / "chat_auth.py").write_text(
        "from flask import Blueprint\n\n"
        "chat_auth_bp = Blueprint('chat_auth', __name__)\n",
        encoding="utf-8",
    )
    (backend_root / "app.py").write_text(
        "from flask import Flask\n"
        "from chat_auth import chat_auth_bp\n"
        "from routes.order import order_bp\n\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    app.register_blueprint(chat_auth_bp, url_prefix='/api')\n"
        "    app.register_blueprint(order_bp, url_prefix='/api')\n"
        "    return app\n",
        encoding="utf-8",
    )

    result = run_flask_host_import_smoke(
        host_workspace=tmp_path,
        entrypoint="app.py",
    )

    assert result.passed is False
    assert result.failure_code == "host_backend_import_failed"
    assert "app.py" in result.related_files
    assert "routes/order.py" in result.related_files
    assert "chat_auth.py" in result.related_files


def test_compile_flask_backend_bundle_computes_import_from_runtime_boundary(tmp_path: Path):
    app_path = tmp_path / "backend" / "api" / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(
        "from flask import Flask\n\n"
        "app = Flask(__name__)\n"
        'app.config["TESTING"] = True\n',
        encoding="utf-8",
    )

    bundle = compile_flask_backend_bundle(
        source_root=tmp_path,
        plan=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/api/app.py",
            import_target="backend/api/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/users.py",
            generated_handler_path="backend/generated/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="demo",
        ),
    )

    updated = bundle.operations[0].new
    assert "from generated.chat_auth import chat_auth_blueprint\n" in updated
    assert updated.index("app = Flask(__name__)") < updated.index(
        'app.register_blueprint(chat_auth_blueprint, url_prefix="/api/chat")'
    )


def test_compile_flask_backend_bundle_rejects_unsupported_wiring(tmp_path: Path):
    app_path = tmp_path / "backend" / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(
        "from flask import Flask\n\n"
        "def build_app():\n"
        "    app = Flask(__name__)\n"
        "    return app\n",
        encoding="utf-8",
    )

    try:
        compile_flask_backend_bundle(
            source_root=tmp_path,
            plan=HostBackendPlan(
                strategy="flask_app_register_blueprint",
                route_target="backend/app.py",
                import_target="backend/app.py",
                login_endpoint="/api/auth/login",
                auth_handler_source="backend/users.py",
                generated_handler_path="backend/chat_auth.py",
                chat_auth_contract_path="/api/chat/auth-token",
                site_id="demo",
            ),
        )
    except ValueError as exc:
        assert "flask_unsupported_wiring_pattern" in str(exc)
    else:
        raise AssertionError("unsupported Flask wiring should fail compilation")
