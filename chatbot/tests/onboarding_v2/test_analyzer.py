import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot


def test_analyzer_builds_food_snapshot():
    source_root = ROOT / "food"
    snapshot = build_analysis_snapshot(site="food", source_root=source_root)

    assert snapshot.repo_profile.backend_framework == "django"
    assert snapshot.repo_profile.frontend_framework == "react"
    assert any(candidate.path.endswith("backend/foodshop/urls.py") for candidate in snapshot.backend_seams.route_registration_points)
    assert any(candidate.path.endswith("frontend/src/App.js") for candidate in snapshot.frontend_seams.app_shell_candidates)
    assert any(candidate.path.endswith("frontend/src/api/api.js") for candidate in snapshot.frontend_seams.api_client_candidates)
