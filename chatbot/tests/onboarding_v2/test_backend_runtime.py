import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot, BackendSeams, DomainIntegration, FrontendSeams, RepoProfile
from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    BackendWiringPlan,
    FrontendIntegrationPlan,
    IntegrationPlan,
)
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePrepResult
from chatbot.src.onboarding_v2.validation.backend_runtime import build_backend_runtime_plan


def _snapshot(*, backend_framework: str, backend_entrypoints: list[str] | None = None) -> AnalysisSnapshot:
    return AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="demo",
            source_root="/tmp/demo",
            backend_framework=backend_framework,
            frontend_framework="react",
            auth_style="session_cookie",
            backend_entrypoints=list(backend_entrypoints or []),
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(),
    )


def _plan(*, strategy: str) -> IntegrationPlan:
    return IntegrationPlan(
        host_backend=BackendWiringPlan(
            strategy=strategy,
            route_target="backend/config/urls.py",
            import_target="backend/config/urls.py",
            auth_handler_source="backend/users/views.py",
            site_id="demo",
        ),
        host_frontend=FrontendIntegrationPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="demo",
            adapter_package="src/adapters/generated/demo",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_DEMO_API_URL",
        ),
    )


def test_build_backend_runtime_plan_for_django(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
        plan=_plan(strategy="django_project_urlconf_import_view"),
        prep_result=BackendRuntimePrepResult(framework="django", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.command == ["/tmp/python", "manage.py", "runserver", "127.0.0.1:8000"]
    assert runtime_plan.readiness_url.endswith("/api/chat/auth-token")


def test_build_backend_runtime_plan_for_flask(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "app.py").write_text("app = object()\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="flask", backend_entrypoints=["backend/app.py"]),
        plan=_plan(strategy="flask_app_register_blueprint"),
        prep_result=BackendRuntimePrepResult(framework="flask", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.command == ["/tmp/python", "app.py"]


def test_build_backend_runtime_plan_for_fastapi(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "main.py").write_text("app = object()\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="fastapi", backend_entrypoints=["backend/main.py"]),
        plan=_plan(strategy="fastapi_include_router"),
        prep_result=BackendRuntimePrepResult(framework="fastapi", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.command == [
        "/tmp/python",
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
