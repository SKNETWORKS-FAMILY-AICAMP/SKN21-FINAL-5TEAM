from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.debug_logging import (
    append_execution_trace,
    append_generation_log,
    append_onboarding_event,
    append_recovery_event,
)


def test_append_onboarding_event_writes_human_log_and_canonical_jsonl(tmp_path: Path):
    reports_root = tmp_path / "reports"

    paths = append_onboarding_event(
        report_root=reports_root,
        run_id="food-run-001",
        component="orchestrator",
        stage="analysis",
        event="stage_started",
        severity="info",
        summary="analysis started",
        source="system",
        details={"site": "food"},
        related_files=["backend/users/views.py"],
        next_action="build codebase map",
    )

    generation_lines = paths["generation_log_path"].read_text(encoding="utf-8").splitlines()
    event_lines = [
        json.loads(line)
        for line in paths["event_log_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert paths["generation_log_path"].name == "generation.log"
    assert paths["event_log_path"].name == "execution-trace.jsonl"
    assert len(generation_lines) == 1
    assert "INFO orchestrator stage_started analysis started" in generation_lines[0]
    assert "stage=analysis" in generation_lines[0]
    assert "site=food" in generation_lines[0]

    assert event_lines == [
        {
            "timestamp": event_lines[0]["timestamp"],
            "run_id": "food-run-001",
            "component": "orchestrator",
            "stage": "analysis",
            "event": "stage_started",
            "severity": "info",
            "summary": "analysis started",
            "source": "system",
            "details": {"site": "food"},
            "related_files": ["backend/users/views.py"],
            "next_action": "build codebase map",
        }
    ]


def test_append_generation_log_creates_timeline_file_and_appends_entries(tmp_path: Path):
    reports_root = tmp_path / "reports"

    first_path = append_generation_log(
        report_root=reports_root,
        level="INFO",
        component="orchestrator",
        event="analysis_started",
        message="analysis started",
        details={"site": "food"},
    )
    second_path = append_generation_log(
        report_root=reports_root,
        level="WARN",
        component="codebase_mapper",
        event="llm_codebase_interpretation_fallback",
        message="payload validation failed",
        details={"reason": "invalid_llm_payload"},
    )

    lines = first_path.read_text(encoding="utf-8").splitlines()

    assert first_path == second_path
    assert first_path.name == "generation.log"
    assert len(lines) == 2
    assert "INFO orchestrator analysis_started analysis started" in lines[0]
    assert "site=food" in lines[0]
    assert "WARN codebase_mapper llm_codebase_interpretation_fallback payload validation failed" in lines[1]
    assert "reason=invalid_llm_payload" in lines[1]


def test_debug_logging_wrappers_write_canonical_events_and_recovery_artifact(tmp_path: Path):
    reports_root = tmp_path / "reports"

    generation_path = append_generation_log(
        report_root=reports_root,
        level="INFO",
        component="orchestrator",
        event="analysis_started",
        message="analysis started",
        details={"site": "food"},
    )
    trace_path = append_execution_trace(
        report_root=reports_root,
        event="analysis_completed",
        status="completed",
        run_id="food-run-001",
        related_files=["backend/users/views.py"],
        details={"site": "food"},
    )
    recovery_path = append_recovery_event(
        report_root=reports_root,
        component="llm_codebase_interpretation",
        source="recovered_llm",
        recovery_reason="framework_assessment_string_to_dict",
    )
    second_recovery_path = append_recovery_event(
        report_root=reports_root,
        component="llm_patch_draft",
        source="hard_fallback",
        hard_fallback_reason="invalid_patch_format",
    )

    recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    event_lines = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pretty_trace_payload = json.loads((reports_root / "execution-trace.json").read_text(encoding="utf-8"))

    assert generation_path.name == "generation.log"
    assert recovery_path == second_recovery_path
    assert recovery_path.name == "recovery-events.json"
    assert recovery_payload == [
        {
            "component": "llm_codebase_interpretation",
            "source": "recovered_llm",
            "recovery_reason": "framework_assessment_string_to_dict",
            "hard_fallback_reason": None,
        },
        {
            "component": "llm_patch_draft",
            "source": "hard_fallback",
            "recovery_reason": None,
            "hard_fallback_reason": "invalid_patch_format",
        },
    ]
    assert [item["event"] for item in event_lines] == [
        "analysis_started",
        "analysis_completed",
        "recovery_applied",
        "hard_fallback_used",
    ]
    assert event_lines[2]["component"] == "llm_codebase_interpretation"
    assert event_lines[2]["source"] == "recovered_llm"
    assert event_lines[2]["recovery"] == {
        "applied": True,
        "reason": "framework_assessment_string_to_dict",
    }
    assert event_lines[3]["component"] == "llm_patch_draft"
    assert event_lines[3]["source"] == "hard_fallback"
    assert event_lines[3]["recovery"] == {
        "applied": False,
        "reason": "invalid_patch_format",
    }
    assert pretty_trace_payload == event_lines


def test_append_onboarding_event_renders_source_debug_path_and_recovery_reason_in_generation_log(tmp_path: Path):
    reports_root = tmp_path / "reports"

    paths = append_onboarding_event(
        report_root=reports_root,
        run_id="food-run-002",
        component="patch_planner",
        stage="generation",
        event="hard_fallback_used",
        severity="warn",
        summary="patch proposal used hard fallback",
        source="hard_fallback",
        recovery={"applied": False, "reason": "invalid_llm_payload"},
        details={"fallback_reason": "invalid_llm_payload"},
        debug_artifact_path="reports/llm-debug/patch-proposal.json",
    )

    line = paths["generation_log_path"].read_text(encoding="utf-8").strip()
    event_payload = json.loads(paths["event_log_path"].read_text(encoding="utf-8").strip())

    assert "WARN patch_planner hard_fallback_used patch proposal used hard fallback" in line
    assert "stage=generation" in line
    assert "source=hard_fallback" in line
    assert "recovery_reason=invalid_llm_payload" in line
    assert "debug_artifact_path=reports/llm-debug/patch-proposal.json" in line
    assert event_payload["debug_artifact_path"] == "reports/llm-debug/patch-proposal.json"
    assert event_payload["recovery"] == {"applied": False, "reason": "invalid_llm_payload"}


def test_append_generation_log_supports_direct_edit_and_export_replay_events(tmp_path: Path):
    reports_root = tmp_path / "reports"

    append_generation_log(
        report_root=reports_root,
        level="INFO",
        component="orchestrator",
        event="edit_plan_written",
        message="edit plan artifact written",
        details={"path": "reports/edit-plan.json"},
    )
    append_generation_log(
        report_root=reports_root,
        level="INFO",
        component="runtime_runner",
        event="export_replay_validation_completed",
        message="export replay validation completed",
        details={"passed": True},
    )

    lines = (reports_root / "generation.log").read_text(encoding="utf-8").splitlines()

    assert "INFO orchestrator edit_plan_written edit plan artifact written" in lines[0]
    assert "path=reports/edit-plan.json" in lines[0]
    assert "INFO runtime_runner export_replay_validation_completed export replay validation completed" in lines[1]
    assert "passed=True" in lines[1]
