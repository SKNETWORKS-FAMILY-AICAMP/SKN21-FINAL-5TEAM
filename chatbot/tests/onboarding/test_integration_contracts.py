import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.integration_contracts import (
    BackendContract,
    FrontendContract,
    SiteIntegrationContract,
)


def test_backend_contract_captures_session_cookie_auth():
    contract = BackendContract(
        framework=" Django ",
        auth_style="SESSION_COOKIE",
        route_registration_points=[
            "backend/users/urls.py",
            "backend/users/urls.py",
            "",
        ],
    )

    assert contract.framework == "django"
    assert contract.auth_style == "session_cookie"
    assert contract.route_registration_points == ["backend/users/urls.py"]
    assert contract.auth_source_paths == []
    assert contract.user_resolver_paths == []


def test_site_integration_contract_normalizes_flask_vue_contracts():
    contract = SiteIntegrationContract(
        site=" Bilyeo ",
        backend={
            "framework": " Flask ",
            "auth_style": "Session",
            "route_registration_points": ["backend/routes/auth.py"],
        },
        frontend={
            "framework": " Vue ",
            "app_shell_path": "frontend/src/App.vue",
            "router_boundary_path": "frontend/src/App.vue",
            "widget_mount_points": [
                "frontend/src/App.vue",
                "frontend/src/App.vue",
            ],
        },
        chat_auth={
            "endpoint_path": " /api/chat/auth-token ",
            "method": "post",
        },
    )

    assert contract.site == "bilyeo"
    assert contract.backend.framework == "flask"
    assert contract.frontend.framework == "vue"
    assert contract.chat_auth.endpoint_path == "/api/chat/auth-token"
    assert contract.chat_auth.method == "POST"
    assert contract.frontend.widget_mount_points == ["frontend/src/App.vue"]


def test_site_integration_contract_defaults_capability_contracts():
    contract = SiteIntegrationContract(
        site="food",
        backend=BackendContract(
            framework="django",
            auth_style="session_cookie",
            route_registration_points=["backend/users/urls.py"],
        ),
        frontend=FrontendContract(
            framework="react",
            app_shell_path="frontend/src/App.js",
            widget_mount_points=["frontend/src/App.js"],
        ),
    )

    assert contract.chat_auth.endpoint_path == "/api/chat/auth-token"
    assert contract.chat_auth.method == "POST"
    assert contract.product_adapter.enabled is False
    assert contract.product_adapter.tool_names == []
    assert contract.order_adapter.enabled is False
    assert contract.order_adapter.tool_names == []
