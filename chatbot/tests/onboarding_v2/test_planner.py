import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.planning import build_integration_plan


def test_planner_selects_food_strategies():
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(snapshot)

    assert plan.backend_wiring.strategy == "django_project_urlconf_import_view"
    assert plan.backend_wiring.route_target == "backend/foodshop/urls.py"
    assert plan.backend_wiring.auth_handler_source == "backend/users/views.py"
    assert plan.frontend_integration.mount_target == "frontend/src/App.js"
    assert plan.frontend_integration.api_client_target == "frontend/src/api/api.js"
