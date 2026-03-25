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
    plan = build_integration_plan(
        snapshot,
        chatbot_server_base_url="http://localhost:8100",
    )
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")
    apply_result = apply_edit_program(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        runtime_root=runtime_root,
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )

    export_bundle_ref, replay_result, replay_ref = export_and_replay(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        host_runtime_workspace=apply_result.host_workspace_path,
        chatbot_runtime_workspace=apply_result.chatbot_workspace_path,
        runtime_root=runtime_root,
        run_root=generated_root,
        site="food",
        run_id="food-run-v2",
        artifact_store=ArtifactStore(generated_root),
    )

    assert export_bundle_ref.version == 1
    assert replay_ref.version == 1
    assert replay_result.passed is True
    assert Path(replay_result.host_replay_workspace_path).exists()
    assert Path(replay_result.chatbot_replay_workspace_path).exists()
    assert replay_result.host_patch_path.endswith("host-approved.patch/v0001.patch")
    assert replay_result.chatbot_patch_path.endswith("chatbot-approved.patch/v0001.patch")
