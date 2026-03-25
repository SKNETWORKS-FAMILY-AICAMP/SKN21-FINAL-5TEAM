import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.planning import build_integration_plan


def test_compiler_builds_complete_food_program():
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(snapshot)
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")

    assert program.backend_wiring_bundles[0].target_paths == ["backend/foodshop/urls.py"]
    assert program.backend_wiring_bundles[0].supporting_files[0].path == "backend/chat_auth.py"
    assert program.frontend_mount_bundles[0].target_path == "frontend/src/App.js"
    assert program.frontend_api_bundles[0].target_path == "frontend/src/api/api.js"
