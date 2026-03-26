import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.storage.event_store import EventStore


def test_event_store_updates_timeline_incrementally(tmp_path: Path):
    store = EventStore(tmp_path / "generated" / "demo" / "demo-run")

    store.write_event(
        run_id="demo-run",
        stage="validation",
        phase="prep_start",
        event_type="backend_runtime_prep_started",
        summary="backend runtime prep started",
    )
    store.write_event(
        run_id="demo-run",
        stage="validation",
        phase="prep_reset_progress",
        event_type="backend_runtime_prep_progress",
        summary="backend runtime prep reset still running",
    )

    timeline_path = tmp_path / "generated" / "demo" / "demo-run" / "views" / "timeline.txt"
    assert timeline_path.exists()
    timeline_lines = timeline_path.read_text(encoding="utf-8").splitlines()
    assert len(timeline_lines) == 2
    assert "backend runtime prep started" in timeline_lines[0]
    assert "backend runtime prep reset still running" in timeline_lines[1]
