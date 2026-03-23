import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.engine import run_onboarding_generation_v2
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePlan, BackendRuntimePrepResult, BackendRuntimeState


def test_food_vertical_slice_generates_all_v2_artifacts(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.run_runtime_smoke",
        lambda **kwargs: {
            "passed": True,
            "results": [],
            "failure_summary": "smoke passed",
            "related_files": [],
        },
    )
    result = run_onboarding_generation_v2(
        site="food",
        source_root=str(ROOT / "food"),
        generated_root=str(tmp_path / "generated"),
        runtime_root=str(tmp_path / "runtime"),
        run_id="food-run-v2",
        onboarding_credentials={"email": "test1@example.com", "password": "password123"},
    )

    run_root = Path(result["run_root"])
    assert result["status"] == "exported"
    assert (run_root / "events" / "events.jsonl").exists()
    assert (run_root / "views" / "run-summary.json").exists()
    assert (run_root / "artifacts" / "01-analysis" / "snapshot" / "v0001.json").exists()
    assert (run_root / "artifacts" / "02-planning" / "integration-plan" / "v0001.json").exists()
    assert (run_root / "artifacts" / "03-compile" / "edit-program" / "v0001.json").exists()
    assert (run_root / "artifacts" / "04-apply" / "apply-result" / "v0001.json").exists()
    assert (run_root / "artifacts" / "05-validation" / "backend-runtime-prep" / "v0001.json").exists()
    assert (run_root / "artifacts" / "05-validation" / "backend-runtime-state" / "v0001.json").exists()
    assert (run_root / "artifacts" / "05-validation" / "smoke-results" / "v0001.json").exists()
    assert (run_root / "artifacts" / "05-validation" / "validation-bundle" / "v0001.json").exists()
    assert (run_root / "artifacts" / "06-export" / "approved-patch" / "v0001.patch").exists()
    assert (run_root / "artifacts" / "06-export" / "replay-result" / "v0001.json").exists()
    summary = json.loads((run_root / "views" / "run-summary.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (run_root / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = {event["event_type"] for event in events}
    assert summary["status"] == "exported"
    assert "backend_runtime_prep_started" in event_types
    assert "backend_runtime_prep_completed" in event_types
    assert "backend_runtime_boot_started" in event_types
    assert "backend_runtime_boot_completed" in event_types
    assert "smoke_started" in event_types
    assert "smoke_completed" in event_types
