from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

import onmo.dashboard as dashboard


def test_decorate_dashboard_payload_builds_story_without_repair():
    payload = {
        "run": {
            "run_id": "food-demo-001",
            "site": "food",
            "status": "running",
            "status_label": "Running",
            "retrieval_status": {},
            "enabled_retrieval_corpora": [],
        },
        "process": {
            "running": True,
            "log_path": "/tmp/onmo.log",
        },
        "stages": [
            {
                "stage": "analysis",
                "label": "Analysis",
                "status": "completed",
                "status_label": "Completed",
                "summary": "analysis completed",
            },
            {
                "stage": "planning",
                "label": "Planning",
                "status": "running",
                "status_label": "Running",
                "summary": "planning started",
            },
            {
                "stage": "compile",
                "label": "Compile",
                "status": "pending",
                "status_label": "Waiting",
                "summary": "",
            },
        ],
        "repair": {"active": False},
        "recent_events": [
            {
                "timestamp": "2026-03-27T12:00:00+00:00",
                "stage": "planning",
                "event_type": "stage_started",
                "summary": "planning started",
                "severity": "info",
            }
        ],
        "repair_events": [],
        "details": {},
    }

    enriched = dashboard.decorate_dashboard_payload(payload)

    assert enriched["story"]["current_stage"]["stage"] == "planning"
    assert enriched["story"]["focus_stage"]["stage"] == "planning"
    assert enriched["story"]["steps"][1]["stage"] == "planning"
    assert enriched["story"]["steps"][1]["emphasis"] == "current"
    assert enriched["story"]["headline"] == "현재 Planning 단계가 진행 중입니다."
    assert enriched["repair_story"]["active"] is False


def test_decorate_dashboard_payload_builds_repair_story_with_rewind():
    payload = {
        "run": {
            "run_id": "food-demo-002",
            "site": "food",
            "status": "running",
            "status_label": "Running",
            "retrieval_status": {},
            "enabled_retrieval_corpora": [],
        },
        "process": {
            "running": True,
            "log_path": "/tmp/onmo.log",
        },
        "stages": [
            {
                "stage": "analysis",
                "label": "Analysis",
                "status": "running",
                "status_label": "Running",
                "summary": "analysis rerun started",
            },
            {
                "stage": "planning",
                "label": "Planning",
                "status": "pending",
                "status_label": "Waiting",
                "summary": "",
            },
            {
                "stage": "compile",
                "label": "Compile",
                "status": "failed",
                "status_label": "Failed",
                "summary": "compile failed",
            },
        ],
        "repair": {
            "active": True,
            "status": "running",
            "status_label": "분석 단계로 되감기",
            "failed_stage": "compile",
            "failed_stage_label": "컴파일",
            "failure_signature": "compile_signature",
            "failure_summary": "widget bundle build failed",
            "requested_rewind_to": "analysis",
            "effective_rewind_to": "analysis",
            "effective_rewind_label": "분석",
            "problem_explanation": "컴파일 단계에서 문제가 발생했습니다. 시스템은 분석 단계로 되감아 다시 확인하려고 합니다.",
            "diagnosis_summary": "컴파일 입력이 불완전해 분석 단계부터 다시 보는 것이 안전합니다.",
            "current_action": "분석 단계부터 다시 실행하도록 결정했습니다.",
            "stop_reason": "",
            "stop_reason_text": "",
            "repeat_count": 1,
            "attempt_number": 1,
        },
        "recent_events": [
            {
                "timestamp": "2026-03-27T12:00:01+00:00",
                "stage": "compile",
                "event_type": "stage_failed",
                "summary": "compile failed",
                "severity": "error",
            },
            {
                "timestamp": "2026-03-27T12:00:03+00:00",
                "stage": "analysis",
                "event_type": "stage_rerun_started",
                "summary": "analysis rerun started",
                "severity": "info",
            },
        ],
        "repair_events": [
            {
                "timestamp": "2026-03-27T12:00:02+00:00",
                "stage": "repair",
                "event_type": "repair_diagnosis_started",
                "summary": "repair diagnosis started",
                "severity": "info",
            },
            {
                "timestamp": "2026-03-27T12:00:02+00:00",
                "stage": "repair",
                "event_type": "repair_decision_emitted",
                "summary": "repair decision emitted",
                "severity": "info",
            },
            {
                "timestamp": "2026-03-27T12:00:02+00:00",
                "stage": "repair",
                "event_type": "rewind_requested",
                "summary": "rewind requested to analysis",
                "severity": "info",
            },
        ],
        "details": {},
    }

    enriched = dashboard.decorate_dashboard_payload(payload)

    assert enriched["story"]["steps"][0]["stage"] == "analysis"
    assert enriched["story"]["steps"][0]["emphasis"] == "current"
    assert enriched["story"]["steps"][2]["stage"] == "compile"
    assert enriched["story"]["steps"][2]["emphasis"] == "failed"
    assert enriched["story"]["focus_stage"]["stage"] == "analysis"
    assert enriched["repair_story"]["active"] is True
    assert enriched["repair_story"]["failed_stage"] == "compile"
    assert enriched["repair_story"]["failed_stage_label"] == "컴파일"
    assert enriched["repair_story"]["rewind_to"] == "analysis"
    assert enriched["repair_story"]["rewind_to_label"] == "분석"
    assert enriched["repair_story"]["problem"] == "컴파일 단계에서 문제가 발생했습니다. 시스템은 분석 단계로 되감아 다시 확인하려고 합니다."
    assert enriched["repair_story"]["diagnosis"] == "컴파일 입력이 불완전해 분석 단계부터 다시 보는 것이 안전합니다."
    assert enriched["repair_story"]["current_action"] == "분석 단계부터 다시 실행하도록 결정했습니다."
    assert [step["kind"] for step in enriched["repair_story"]["steps"]] == [
        "failure",
        "diagnosis",
        "rewind",
        "rerun",
    ]


def test_decorate_dashboard_payload_builds_retrieval_story():
    payload = {
        "run": {
            "run_id": "food-demo-003",
            "site": "food",
            "status": "running",
            "status_label": "Running",
            "retrieval_status": {
                "faq": {"status": "completed", "documents_indexed": 12, "smoke_passed": True},
                "policy": {"status": "running", "documents_indexed": 0, "smoke_passed": False},
            },
            "enabled_retrieval_corpora": ["faq", "policy"],
        },
        "process": {
            "running": True,
            "log_path": "/tmp/onmo.log",
        },
        "stages": [
            {
                "stage": "export",
                "label": "Export",
                "status": "completed",
                "status_label": "Completed",
                "summary": "export completed",
            },
            {
                "stage": "validation",
                "label": "Validation",
                "status": "running",
                "status_label": "Running",
                "summary": "validation started",
            },
        ],
        "repair": {"active": False},
        "recent_events": [],
        "repair_events": [],
        "details": {},
    }

    enriched = dashboard.decorate_dashboard_payload(payload)

    assert enriched["story"]["retrieval"]["active"] is True
    assert enriched["story"]["retrieval"]["headline"] == "Retrieval Ready"
    assert enriched["story"]["retrieval"]["items"][0]["corpus"] == "faq"
    assert enriched["story"]["retrieval"]["items"][0]["status"] == "ready"
    assert enriched["story"]["retrieval"]["items"][1]["status"] == "indexing"
