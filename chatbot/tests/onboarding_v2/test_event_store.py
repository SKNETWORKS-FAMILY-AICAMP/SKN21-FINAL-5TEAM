import json
import os
import sys
import threading
import time
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


def test_event_store_serializes_concurrent_writes_with_lock(tmp_path: Path, monkeypatch):
    store = EventStore(tmp_path / "generated" / "demo" / "demo-run")
    original_open = Path.open
    state = {"active": 0, "overlap": False}
    state_lock = threading.Lock()

    class _TrackedContext:
        def __init__(self, handle) -> None:
            self._handle = handle

        def __enter__(self):
            with state_lock:
                state["active"] += 1
                if state["active"] > 1:
                    state["overlap"] = True
            time.sleep(0.01)
            return self._handle.__enter__()

        def __exit__(self, exc_type, exc, tb):
            try:
                return self._handle.__exit__(exc_type, exc, tb)
            finally:
                time.sleep(0.01)
                with state_lock:
                    state["active"] -= 1

    def _tracked_open(path_self: Path, *args, **kwargs):
        handle = original_open(path_self, *args, **kwargs)
        if path_self in {store.events_path, store.timeline_path}:
            return _TrackedContext(handle)
        return handle

    monkeypatch.setattr(Path, "open", _tracked_open)

    thread_count = 6
    barrier = threading.Barrier(thread_count)

    def _write_event(index: int) -> None:
        barrier.wait()
        store.write_event(
            run_id="demo-run",
            stage="analysis",
            phase=f"phase-{index}",
            event_type="stage_progress",
            summary=f"analysis progress {index}",
        )

    threads = [threading.Thread(target=_write_event, args=(index,)) for index in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert state["overlap"] is False
    events = [json.loads(line) for line in store.events_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == thread_count
