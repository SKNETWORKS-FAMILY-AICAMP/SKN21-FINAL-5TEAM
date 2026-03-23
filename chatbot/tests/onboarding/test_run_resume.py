import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.run_resume import analyze_run_checkpoint


def test_analyze_run_checkpoint_detects_completed_export(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-304"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": True, "failure_count": 0}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "frontend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "export-metadata.json").write_text(
        json.dumps({"patch_path": "approved.patch"}),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.last_completed_stage == "export"
    assert checkpoint.failed_stage is None
    assert checkpoint.resume_from_stage is None


def test_analyze_run_checkpoint_detects_export_replay_failure_and_resume_target(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-304-replay"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "edit-plan.json").write_text(json.dumps({"operations": []}), encoding="utf-8")
    (run_root / "reports" / "merge-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "frontend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": True, "failure_count": 0}),
        encoding="utf-8",
    )
    (run_root / "reports" / "export-metadata.json").write_text(
        json.dumps(
            {
                "patch_path": str(run_root / "reports" / "approved.patch"),
                "replay_report_path": str(run_root / "reports" / "export-replay-validation.json"),
                "replay_passed": False,
            }
        ),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.last_completed_stage == "validation"
    assert checkpoint.failed_stage == "export"
    assert checkpoint.resume_from_stage == "export"


def test_analyze_run_checkpoint_detects_validation_failure_and_resume_target(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-324"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (run_root / "reports" / "merge-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text(
        json.dumps({"backend_bootstrap": {"bootstrap_attempted": True, "bootstrap_passed": True}}),
        encoding="utf-8",
    )
    (run_root / "reports" / "frontend-evaluation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "frontend-build-validation.json").write_text(
        json.dumps(
            {
                "bootstrap_failure_stage": "build_environment_failed",
                "bootstrap_failure_reason": "react-scripts failed",
            }
        ),
        encoding="utf-8",
    )
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": False, "failure_count": 1}),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.last_completed_stage == "generation"
    assert checkpoint.failed_stage == "validation"
    assert checkpoint.resume_from_stage == "validation"
    assert "react-scripts failed" in checkpoint.reason


def test_analyze_run_checkpoint_detects_export_resume_point(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-325"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (run_root / "reports" / "codebase-map.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (run_root / "reports" / "merge-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    (run_root / "reports" / "backend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "frontend-evaluation.json").write_text("{}", encoding="utf-8")
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps({"passed": True, "failure_count": 0}),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.last_completed_stage == "validation"
    assert checkpoint.failed_stage is None
    assert checkpoint.resume_from_stage == "export"


def test_analyze_run_checkpoint_reads_repair_history_metadata(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-326"
    reports = run_root / "reports"
    reports.mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (reports / "codebase-map.json").write_text("{}", encoding="utf-8")
    (reports / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    (reports / "merge-simulation.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (reports / "smoke-summary.json").write_text(
        json.dumps({"passed": False, "failure_count": 1}),
        encoding="utf-8",
    )
    (reports / "repair-history.json").write_text(
        json.dumps(
            {
                "site": "food",
                "run_id": "food-run-326",
                "failure_signature": "response_schema_mismatch:chat_auth_token",
                "failure_count_for_signature": 2,
                "repair_scope": "run_only",
            }
        ),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.latest_failure_signature == "response_schema_mismatch:chat_auth_token"
    assert checkpoint.failure_count_for_signature == 2
    assert checkpoint.repair_history_path.endswith("reports/repair-history.json")


def test_analyze_run_checkpoint_treats_edit_plan_as_generation_artifact(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-327"
    reports = run_root / "reports"
    reports.mkdir(parents=True)
    (run_root / "manifest.json").write_text(json.dumps({"analysis": {}}), encoding="utf-8")
    (reports / "codebase-map.json").write_text("{}", encoding="utf-8")
    (reports / "patch-proposal.json").write_text("{}", encoding="utf-8")
    (reports / "edit-plan.json").write_text(json.dumps({"operations": []}), encoding="utf-8")
    (reports / "merge-simulation.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (reports / "smoke-summary.json").write_text(
        json.dumps({"passed": False, "failure_count": 1}),
        encoding="utf-8",
    )

    checkpoint = analyze_run_checkpoint(run_root)

    assert checkpoint.last_completed_stage == "generation"
    assert checkpoint.failed_stage == "validation"
    assert checkpoint.resume_from_stage == "validation"
