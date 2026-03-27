from __future__ import annotations

import os
import sys
import json
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
    assert enriched["story"]["ui"]["headline"] == "계획 단계 진행 중"
    assert enriched["story"]["ui"]["steps"][1]["label"] == "계획"
    assert enriched["recent_events"][0]["display_summary"] == "계획 단계 시작"
    assert enriched["repair_story"]["active"] is False


def test_load_run_dashboard_keeps_full_recent_event_history(tmp_path: Path):
    run_root = tmp_path / "generated-v2" / "food" / "food-demo-999"
    (run_root / "events").mkdir(parents=True)
    (run_root / "views").mkdir(parents=True)
    (run_root / "run.json").write_text(
        json.dumps({"run_id": "food-demo-999", "site": "food"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_root / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "running"}, ensure_ascii=False),
        encoding="utf-8",
    )

    events = []
    for index in range(20):
        events.append(
            {
                "timestamp": f"2026-03-27T12:{index:02d}:00+00:00",
                "stage": "analysis",
                "event_type": "stage_started" if index == 0 else "stage_rerun_started",
                "summary": f"analysis event {index}",
                "severity": "info",
            }
        )
    (run_root / "events" / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    payload = dashboard.load_run_dashboard(run_root=run_root)

    assert len(payload["recent_events"]) == 20
    assert payload["recent_events"][0]["summary"] == "analysis event 0"
    assert payload["recent_events"][-1]["summary"] == "analysis event 19"


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
    assert enriched["story"]["ui"]["connector_label"] == "분석 단계로 되돌아감"
    assert enriched["story"]["ui"]["rerun_lane_label"] == "분석부터 다시 실행"
    assert [card["key"] for card in enriched["repair_story"]["ui"]["summary_cards"]] == [
        "failure",
        "error",
        "diagnosis",
        "rewind",
    ]
    assert enriched["repair_story"]["ui"]["summary_cards"][0]["title"] == "문제 발생"
    assert enriched["repair_story"]["ui"]["summary_cards"][0]["headline"] == "컴파일 단계"
    assert enriched["repair_story"]["ui"]["summary_cards"][0]["detail"] == ""
    assert enriched["repair_story"]["ui"]["summary_cards"][2]["title"] == "진단 판단"
    assert enriched["repair_story"]["ui"]["summary_cards"][3]["detail"] == "분석 단계부터 다시 실행하도록 결정했습니다."
    assert enriched["repair_story"]["ui"]["status_line"] == "분석 단계부터 다시 실행하도록 결정했습니다."
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
    assert enriched["story"]["retrieval"]["headline"] == "인덱싱 준비"
    assert enriched["story"]["retrieval"]["items"][0]["corpus"] == "faq"
    assert enriched["story"]["retrieval"]["items"][0]["status"] == "ready"
    assert enriched["story"]["retrieval"]["items"][1]["status"] == "indexing"


def test_decorate_dashboard_payload_promotes_indexing_to_formal_stage():
    payload = {
        "run": {
            "run_id": "food-demo-004",
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
                "stage": "indexing",
                "label": "Indexing",
                "status": "running",
                "status_label": "Running",
                "summary": "indexing started",
            },
            {
                "stage": "validation",
                "label": "Validation",
                "status": "pending",
                "status_label": "Waiting",
                "summary": "",
            },
        ],
        "repair": {"active": False},
        "recent_events": [
            {
                "timestamp": "2026-03-27T12:00:00+00:00",
                "stage": "indexing",
                "event_type": "stage_started",
                "summary": "indexing started",
                "severity": "info",
            }
        ],
        "repair_events": [],
        "details": {
            "indexing": {
                "cards": [{"label": "Corpora", "value": 2}],
                "corpora": [],
                "smoke_checks": [],
            }
        },
    }

    enriched = dashboard.decorate_dashboard_payload(payload)

    assert [step["stage"] for step in enriched["story"]["steps"]] == ["export", "indexing", "validation"]
    assert enriched["story"]["current_stage"]["stage"] == "indexing"
    assert enriched["story"]["focus_stage"]["stage"] == "indexing"
    assert enriched["story"]["steps"][1]["label"] == "Indexing"
    assert enriched["story"]["steps"][1]["emphasis"] == "current"


def test_load_run_dashboard_builds_analysis_live_payload_and_rich_recent_events(tmp_path: Path):
    run_root = tmp_path / "generated-v2" / "food" / "food-demo-live-analysis"
    (run_root / "events").mkdir(parents=True)
    (run_root / "views").mkdir(parents=True)
    (run_root / "run.json").write_text(
        json.dumps({"run_id": "food-demo-live-analysis", "site": "food"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_root / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "running"}, ensure_ascii=False),
        encoding="utf-8",
    )
    events = [
        {
            "timestamp": "2026-03-27T12:00:00+00:00",
            "stage": "analysis",
            "phase": "start",
            "event_type": "stage_started",
            "summary": "analysis started",
            "severity": "info",
            "attempt": 1,
            "artifact_refs": [],
            "input_refs": [],
            "details": {},
            "source": "deterministic",
        },
        {
            "timestamp": "2026-03-27T12:00:01+00:00",
            "stage": "analysis",
            "phase": "candidate_harvest",
            "event_type": "analysis_candidate_harvest_completed",
            "summary": "analysis candidate harvest completed",
            "severity": "info",
            "attempt": 1,
            "artifact_refs": [],
            "input_refs": [],
            "details": {"candidate_count": 32},
            "source": "deterministic",
        },
        {
            "timestamp": "2026-03-27T12:00:03+00:00",
            "stage": "analysis",
            "phase": "contract-extraction-r0",
            "event_type": "llm_phase_progress",
            "summary": "contract-extraction-r0 llm phase still running",
            "severity": "info",
            "attempt": 1,
            "artifact_refs": [
                {
                    "stage": "analysis",
                    "artifact_type": "analysis-bundle",
                    "version": 1,
                    "path": "v0001.json",
                    "content_hash": "hash-1",
                }
            ],
            "input_refs": [
                {
                    "stage": "analysis",
                    "artifact_type": "snapshot",
                    "version": 1,
                    "path": "v0001.json",
                    "content_hash": "hash-2",
                }
            ],
            "details": {
                "status": "running",
                "provider": "openai",
                "model": "gpt-5.2",
                "elapsed_ms": 5425,
                "tool_call_count": 9,
            },
            "source": "llm",
        },
    ]
    (run_root / "events" / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    payload = dashboard.load_run_dashboard(
        run_root=run_root,
        process=dashboard.ProcessSnapshot(running=True),
    )

    analysis_stage = next(item for item in payload["stages"] if item["stage"] == "analysis")

    assert analysis_stage["summary"] == "계약 추출 진행 중"
    assert payload["recent_events"][-1]["attempt"] == 1
    assert payload["recent_events"][-1]["source"] == "llm"
    assert payload["recent_events"][-1]["details"]["tool_call_count"] == 9
    assert payload["recent_events"][-1]["artifact_ref_count"] == 1
    assert payload["recent_events"][-1]["input_ref_count"] == 1
    assert payload["details"]["analysis"]["live"]["active_phase"] == "contract-extraction-r0"
    assert payload["details"]["analysis"]["live"]["phase_label"] == "계약 추출"
    assert payload["details"]["analysis"]["live"]["status"] == "running"
    assert payload["details"]["analysis"]["live"]["provider"] == "openai"
    assert payload["details"]["analysis"]["live"]["model"] == "gpt-5.2"
    assert payload["details"]["analysis"]["live"]["metrics"][0] == {"label": "후보", "value": "32"}


def test_build_validation_details_ignores_legacy_non_dict_flow_report_entries():
    details = dashboard._build_validation_details(
        validation_bundle={"passed": True, "failure_summary": ""},
        validation_checks=[],
        backend_runtime_state={"passed": True, "framework": "django"},
        widget_bundle_fetch={"passed": True, "target_url": "http://127.0.0.1:8100/widget.js"},
        host_auth_bootstrap={"login_url": "http://127.0.0.1:5000/login", "bootstrap_url": "http://127.0.0.1:5000/api/chat/auth-token"},
        chatbot_adapter_auth={"validated_user": {"id": "7"}},
        widget_order_e2e={
            "passed": True,
            "covered_flows": ["list_orders"],
            "flow_reports": {
                "list_orders": {"passed": True, "failure_summary": ""},
                "module_origins": {"server_fastapi": "/tmp/runtime/server_fastapi.py"},
                "runtime_harness_origin": "workspace",
            },
            "sampled_order_id": "order-1",
        },
    )

    assert details["passed"] is True
    assert details["flow_reports"] == [
        {
            "name": "list_orders",
            "passed": True,
            "summary": "flow passed",
        }
    ]
    assert details["sampled_order_id"] == "order-1"


def test_load_run_dashboard_builds_planning_live_issue_from_fallback_reason(tmp_path: Path):
    run_root = tmp_path / "generated-v2" / "food" / "food-demo-live-planning"
    (run_root / "events").mkdir(parents=True)
    (run_root / "views").mkdir(parents=True)
    (run_root / "run.json").write_text(
        json.dumps({"run_id": "food-demo-live-planning", "site": "food"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_root / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "running"}, ensure_ascii=False),
        encoding="utf-8",
    )
    fallback_reason = "\n".join(
        [
            "3 validation errors for _StrategyEnvelope",
            "strategy_candidates.0.tradeoffs",
            "  Input should be a valid list [type=list_type, input_value='Pros: aligns with existing...', input_type=str]",
            "strategy_candidates.1.tradeoffs",
            "  Input should be a valid list [type=list_type, input_value='Pros: preserves existing...', input_type=str]",
        ]
    )
    events = [
        {
            "timestamp": "2026-03-27T12:01:00+00:00",
            "stage": "planning",
            "phase": "start",
            "event_type": "stage_started",
            "summary": "planning started",
            "severity": "info",
            "attempt": 1,
            "artifact_refs": [],
            "input_refs": [],
            "details": {},
            "source": "deterministic",
        },
        {
            "timestamp": "2026-03-27T12:01:04+00:00",
            "stage": "planning",
            "phase": "strategy-synthesis",
            "event_type": "llm_phase_fallback",
            "summary": "strategy-synthesis llm phase fell back",
            "severity": "info",
            "attempt": 1,
            "artifact_refs": [],
            "input_refs": [],
            "details": {
                "status": "fallback",
                "provider": "openai",
                "model": "gpt-5.2",
                "elapsed_ms": 8884,
                "tool_call_count": 0,
                "fallback_reason": fallback_reason,
            },
            "source": "llm",
        },
    ]
    (run_root / "events" / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    payload = dashboard.load_run_dashboard(
        run_root=run_root,
        process=dashboard.ProcessSnapshot(running=True),
    )
    live = payload["details"]["planning"]["live"]

    assert live["active_phase"] == "strategy-synthesis"
    assert live["phase_label"] == "전략 후보 정리"
    assert live["status"] == "fallback"
    assert "tradeoffs" in live["issue"]
    assert "validation errors for _StrategyEnvelope" not in live["issue"]
    assert "\n" not in live["issue"]
    assert len(live["issue"]) < 120
