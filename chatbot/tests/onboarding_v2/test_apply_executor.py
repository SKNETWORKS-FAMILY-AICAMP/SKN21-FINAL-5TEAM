import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.planning import build_integration_plan


def test_apply_executor_materializes_food_changes(tmp_path: Path):
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(snapshot)
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")

    result = apply_edit_program(
        source_root=ROOT / "food",
        runtime_root=tmp_path / "runtime",
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )

    workspace = Path(result.workspace_path)
    assert result.passed is True
    assert (workspace / "backend" / "chat_auth.py").exists()
    assert "__ORDER_CS_WIDGET_HOST_CONTRACT__" in (workspace / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert "/api/chat/auth-token" in (workspace / "frontend" / "src" / "api" / "api.js").read_text(encoding="utf-8")
