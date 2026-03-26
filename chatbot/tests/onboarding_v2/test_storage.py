import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.storage import ArtifactStore, EventStore, LlmUsageStore, RunStore, ViewProjector


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
    latest_stage_status = json.loads((run_root / "views" / "latest-stage-status.json").read_text(encoding="utf-8"))
    timeline = (run_root / "views" / "timeline.txt").read_text(encoding="utf-8")
    assert latest_stage_status["run_id"] == "food-run-v2"
    assert latest_stage_status["stages"][0]["stage"] == "analysis"
    assert "analysis stage_completed analysis completed" in timeline


def test_run_store_writes_top_level_metadata(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-v2"
    run_store = RunStore(run_root)

    run_store.write_run_metadata(
        site="food",
        source_root="/tmp/food",
        run_id="food-run-v2",
        agent_version="dev",
    )
    run_store.write_manifest(
        site="food",
        source_root="/tmp/food",
        run_id="food-run-v2",
        credentials={"email": "test1@example.com"},
    )

    run_payload = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    manifest_payload = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert run_payload["engine"] == "v2"
    assert manifest_payload["credentials"]["email"] == "test1@example.com"


def test_llm_usage_store_writes_cost_summary(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-v2"
    usage_store = LlmUsageStore(run_root)

    usage_store.append(
        stage="analysis",
        phase="retrieval-plan",
        attempt=1,
        provider="openai",
        model="gpt-5-mini",
        usage={
            "input_tokens": 1200,
            "output_tokens": 300,
            "cached_input_tokens": 200,
            "total_tokens": 1500,
        },
        extra={"status": "parsed"},
    )

    summary_path = run_root / "debug" / "llm-usage-summary.json"
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary_payload["totals"] == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cached_input_tokens": 200,
        "total_tokens": 1500,
        "estimated_input_cost_usd": 0.00025,
        "estimated_output_cost_usd": 0.0006,
        "estimated_cached_input_cost_usd": 0.000005,
        "estimated_total_cost_usd": 0.000855,
    }
    assert summary_payload["pricing"] == {
        "input_cost_per_1m": 0.25,
        "output_cost_per_1m": 2.0,
        "cached_input_cost_per_1m": 0.025,
        "pricing_source": "openai_public_pricing_2026-03-16",
    }
    assert summary_payload["calls"][0]["stage"] == "analysis"
    assert summary_payload["calls"][0]["estimated_total_cost_usd"] == 0.000855
