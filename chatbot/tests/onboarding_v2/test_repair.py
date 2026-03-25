import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models import ArtifactRef, FailureBundle
from chatbot.src.onboarding_v2.repair import diagnose_failure, synthesize_failure
from chatbot.src.onboarding_v2.storage import DebugStore


def test_synthesize_failure_collects_related_file_samples(tmp_path: Path):
    workspace = tmp_path / "workspace"
    target = workspace / "backend" / "orders" / "views.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def list_orders(request):\n    return {'orders': []}\n", encoding="utf-8")

    bundle = synthesize_failure(
        failed_stage="compile",
        failure_signature="compile_failed",
        failure_summary="compile failed",
        trigger_event_id="evt-1",
        related_artifacts=[
            ArtifactRef(
                stage="compile",
                artifact_type="edit-program",
                version=1,
                path="v0001.json",
                content_hash="hash",
            )
        ],
        related_files=["backend/orders/views.py"],
        workspace_root=workspace,
        input_artifact_versions={"compile": 1},
        attempt_number=2,
        repeat_count=1,
    )

    assert bundle.failure_signature == "compile_failed"
    assert bundle.related_file_samples[0]["path"] == "backend/orders/views.py"
    assert "list_orders" in bundle.related_file_samples[0]["content"]


def test_diagnose_failure_returns_stop_when_llm_unavailable(tmp_path: Path):
    debug_store = DebugStore(tmp_path / "generated" / "food" / "food-run-v2")
    failure_bundle = FailureBundle(
        failed_stage="validation",
        failure_signature="smoke_failed",
        failure_summary="step order-api returned 500",
        trigger_event_id="evt-2",
        related_artifacts=[],
        related_files=[],
        related_file_samples=[],
        input_artifact_versions={"validation": 1},
        attempt_number=1,
        repeat_count=1,
    )

    decision = diagnose_failure(
        failure_bundle=failure_bundle,
        snapshot_payload={"repo_profile": {"site": "food"}},
        plan_payload={},
        edit_program_payload={},
        validation_payload={"passed": False},
        llm_provider="openai",
        llm_model="gpt-5-mini",
        debug_store=debug_store,
        llm_factory=lambda: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
    )

    assert decision.stop is True
    assert decision.stop_reason == "repair_llm_unavailable"


def test_diagnose_failure_parses_v2_repair_decision(tmp_path: Path):
    debug_store = DebugStore(tmp_path / "generated" / "food" / "food-run-v2")
    failure_bundle = FailureBundle(
        failed_stage="validation",
        failure_signature="smoke_failed",
        failure_summary="step login returned 500",
        trigger_event_id="evt-3",
        related_artifacts=[],
        related_files=[],
        related_file_samples=[],
        input_artifact_versions={"validation": 1},
        attempt_number=1,
        repeat_count=1,
    )

    class _Response:
        content = json.dumps(
            {
                "failure_signature": "smoke_failed",
                "diagnosis": "login smoke should be rerun from validation",
                "rewind_to": "validation",
                "preserve_artifacts": ["analysis", "planning", "compile", "apply", "export"],
                "required_rechecks": ["smoke"],
                "additional_discovery": [],
                "artifact_overrides": {},
                "stop": False,
                "stop_reason": None,
            }
        )

    class _LLM:
        def invoke(self, _messages):
            return _Response()

    decision = diagnose_failure(
        failure_bundle=failure_bundle,
        snapshot_payload={"repo_profile": {"site": "food"}},
        plan_payload={},
        edit_program_payload={},
        validation_payload={"passed": False},
        llm_provider="openai",
        llm_model="gpt-5-mini",
        debug_store=debug_store,
        llm_factory=lambda: _LLM(),
    )

    assert decision.stop is False
    assert decision.rewind_to == "validation"
