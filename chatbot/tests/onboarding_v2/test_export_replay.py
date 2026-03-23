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
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.planning import build_integration_plan
from chatbot.src.onboarding_v2.storage import ArtifactStore


def test_export_replay_applies_exported_patch(tmp_path: Path):
    generated_root = tmp_path / "generated" / "food" / "food-run-v2"
    runtime_root = tmp_path / "runtime"
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(snapshot)
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")
    apply_result = apply_edit_program(
        source_root=ROOT / "food",
        runtime_root=runtime_root,
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )

    patch_ref, replay_result, replay_ref = export_and_replay(
        source_root=ROOT / "food",
        runtime_workspace=apply_result.workspace_path,
        runtime_root=runtime_root,
        run_root=generated_root,
        site="food",
        run_id="food-run-v2",
        artifact_store=ArtifactStore(generated_root),
    )

    assert patch_ref.version == 1
    assert replay_ref.version == 1
    assert replay_result.passed is True
    assert Path(replay_result.replay_workspace_path).exists()
