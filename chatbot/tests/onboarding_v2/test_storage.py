import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.storage import ArtifactStore, EventStore, ViewProjector


def test_event_and_artifact_store_round_trip(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-v2"
    artifact_store = ArtifactStore(run_root)
    event_store = EventStore(run_root)

    event = event_store.write_event(
        run_id="food-run-v2",
        stage="analysis",
        phase="start",
        event_type="stage_started",
        summary="analysis started",
    )
    artifact_ref = artifact_store.write_json_artifact(
        stage="analysis",
        artifact_type="snapshot",
        payload={"site": "food"},
        producer="test",
        event_ref=event.event_id,
    )

    assert (run_root / "events" / "events.jsonl").exists()
    latest = json.loads(
        (run_root / "artifacts" / "01-analysis" / "snapshot" / "latest.json").read_text(encoding="utf-8")
    )
    assert latest["version"] == 1
    assert artifact_ref.version == 1
    assert (run_root / "artifacts" / "07-repair").exists()


def test_view_projector_builds_summary(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-v2"
    artifact_store = ArtifactStore(run_root)
    event_store = EventStore(run_root)
    event_store.write_event(
        run_id="food-run-v2",
        stage="analysis",
        phase="finish",
        event_type="stage_completed",
        summary="analysis completed",
    )
    artifact_store.write_json_artifact(
        stage="analysis",
        artifact_type="snapshot",
        payload={"site": "food"},
        producer="test",
    )
    summary = ViewProjector(run_root).project(
        run_id="food-run-v2",
        site="food",
        status="pending_compile",
        latest_failure_signature="smoke_failed",
        latest_rewind_to="validation",
        repair_attempt_count=1,
        stopped_for_review=False,
    )

    assert summary.status == "pending_compile"
    assert summary.latest_rewind_to == "validation"
    assert summary.repair_attempt_count == 1
    assert (run_root / "views" / "run-summary.json").exists()
