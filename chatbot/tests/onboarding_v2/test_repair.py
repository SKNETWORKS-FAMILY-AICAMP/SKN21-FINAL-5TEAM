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
from chatbot.src.onboarding_v2.repair.synthesis import collect_file_samples
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


def test_synthesize_failure_enriches_compile_preflight_failures_with_runtime_context(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    server_fastapi = workspace / "server_fastapi.py"
    adapter_tool = workspace / "src" / "tools" / "adapter_order_tools.py"
    server_fastapi.parent.mkdir(parents=True, exist_ok=True)
    adapter_tool.parent.mkdir(parents=True, exist_ok=True)
    server_fastapi.write_text(
        "from src.tools.adapter_order_tools import register_exchange_via_adapter\napp = object()\n",
        encoding="utf-8",
    )
    adapter_tool.write_text(
        "from ecommerce.backend.app.database import SessionLocal\n",
        encoding="utf-8",
    )

    bundle = synthesize_failure(
        failed_stage="compile",
        failure_signature="chatbot_runtime_import_banned_import_detected",
        failure_summary="banned import detected: ecommerce.backend, SessionLocal",
        trigger_event_id="evt-preflight",
        related_artifacts=[
            ArtifactRef(
                stage="compile",
                artifact_type="compile-preflight",
                version=1,
                path="v0001.json",
                content_hash="hash",
            )
        ],
        related_files=["src/tools/adapter_order_tools.py"],
        workspace_root=workspace,
        input_artifact_versions={"compile": 2},
        attempt_number=1,
        repeat_count=1,
    )

    assert bundle.related_files == [
        "server_fastapi.py",
        "src/tools/adapter_order_tools.py",
    ]
    sample_paths = {sample["path"] for sample in bundle.related_file_samples}
    assert "server_fastapi.py" in sample_paths
    assert "src/tools/adapter_order_tools.py" in sample_paths
    context_sample = next(
        sample
        for sample in bundle.related_file_samples
        if sample["path"] == "__failure_context__/compile-preflight.json"
    )
    assert "banned import detected" in context_sample["content"]
    assert "compile-preflight" in context_sample["content"]


def test_collect_file_samples_skips_paths_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    inside = workspace / "src" / "safe.py"
    outside = tmp_path / "outside.py"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("SAFE = True\n", encoding="utf-8")
    outside.write_text("LEAK = True\n", encoding="utf-8")

    samples = collect_file_samples(
        workspace_root=workspace,
        related_files=[
            "src/safe.py",
            "../outside.py",
            str(outside),
        ],
    )

    assert samples == [
        {
            "path": "src/safe.py",
            "content": "SAFE = True",
        }
    ]


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
        analysis_bundle_payload={},
        snapshot_payload={"repo_profile": {"site": "food"}},
        planning_bundle_payload={},
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


def test_diagnose_failure_prefers_compile_rewind_for_import_graph_preflight_failure(
    tmp_path: Path,
):
    debug_store = DebugStore(tmp_path / "generated" / "food" / "food-run-v2")
    failure_bundle = FailureBundle(
        failed_stage="compile",
        failure_signature="chatbot_runtime_import_banned_import_detected",
        failure_summary="banned import detected: ecommerce.backend, SessionLocal",
        trigger_event_id="evt-compile-preflight",
        related_artifacts=[
            ArtifactRef(
                stage="compile",
                artifact_type="compile-preflight",
                version=1,
                path="v0001.json",
                content_hash="hash",
            )
        ],
        related_files=["server_fastapi.py", "src/tools/adapter_order_tools.py"],
        related_file_samples=[
            {"path": "server_fastapi.py", "content": "from src.tools.adapter_order_tools import x\n"},
            {
                "path": "src/tools/adapter_order_tools.py",
                "content": "from ecommerce.backend.app.database import SessionLocal\n",
            },
        ],
        input_artifact_versions={"compile": 2},
        attempt_number=1,
        repeat_count=1,
    )

    decision = diagnose_failure(
        failure_bundle=failure_bundle,
        analysis_bundle_payload={},
        snapshot_payload={"repo_profile": {"site": "food"}},
        planning_bundle_payload={},
        plan_payload={},
        edit_program_payload={},
        validation_payload={},
        llm_provider="openai",
        llm_model="gpt-5-mini",
        debug_store=debug_store,
        llm_factory=lambda: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    assert decision.stop is False
    assert decision.rewind_to == "compile"
    assert decision.required_rechecks == ["compile_preflight"]
    assert "import" in decision.diagnosis.lower()


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
        analysis_bundle_payload={},
        snapshot_payload={"repo_profile": {"site": "food"}},
        planning_bundle_payload={},
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
