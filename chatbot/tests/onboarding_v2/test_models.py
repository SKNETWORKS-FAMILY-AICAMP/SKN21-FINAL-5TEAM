import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models import (
    AnalysisSnapshot,
    ArtifactEnvelope,
    ArtifactRef,
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    BackendSeams,
    BackendWiringPlan,
    DomainIntegration,
    EditProgram,
    FrontendIntegrationPlan,
    FrontendSeams,
    IntegrationPlan,
    PathCandidate,
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
        backend_wiring=BackendWiringPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/foodshop/urls.py",
            import_target="backend/foodshop/urls.py",
            auth_handler_source="backend/users/views.py",
            generated_handler_path="backend/chat_auth.py",
        ),
        frontend_integration=FrontendIntegrationPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
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
    summary = RunSummaryView(run_id="food-run-v2", site="food", status="pending")
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

    assert envelope.payload["repo_profile"]["site"] == "food"
    assert plan.backend_wiring.generated_handler_path == "backend/chat_auth.py"
    assert EditProgram().model_dump()["execution_metadata"] == {}
    assert ValidationBundle(passed=True).passed is True
    assert ArtifactRef(stage="analysis", artifact_type="snapshot", version=1, path="v0001.json", content_hash="x").path == "v0001.json"
    assert summary.status == "pending"
    assert prep.framework == "django"
    assert runtime_plan.readiness_url.endswith("/api/chat/auth-token")
    assert runtime_state.passed is True
