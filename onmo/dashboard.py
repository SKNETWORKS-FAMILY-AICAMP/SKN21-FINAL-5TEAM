from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatbot.src.onboarding_v2.storage.artifact_store import STAGE_DIRECTORY_MAP

STAGE_ORDER = ["analysis", "planning", "compile", "apply", "export", "validation"]
DISPLAY_STAGE_ORDER = ["import", *STAGE_ORDER]
STAGE_LABELS = {
    "import": "Import",
    "analysis": "Analysis",
    "planning": "Planning",
    "compile": "Compile",
    "apply": "Apply",
    "export": "Export",
    "validation": "Validation",
}
STAGE_LABELS_KO = {
    "import": "가져오기",
    "analysis": "분석",
    "planning": "계획",
    "compile": "컴파일",
    "apply": "적용",
    "export": "내보내기",
    "validation": "검증",
    "repair": "복구",
}
STATUS_LABELS = {
    "pending": "Waiting",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "disabled": "Disabled",
    "exported": "Ready",
    "failed_human_review": "Needs Review",
    "process_failed": "Process Failed",
    "unknown": "Unknown",
}


@dataclass(slots=True)
class ProcessSnapshot:
    running: bool
    pid: int | None = None
    command: list[str] | None = None
    log_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    preview_url: str | None = None


def build_import_stage_view(
    *,
    status: str,
    summary: str = "",
    started_at: str = "",
    finished_at: str = "",
) -> dict[str, Any]:
    return {
        "stage": "import",
        "label": STAGE_LABELS["import"],
        "status": status,
        "status_label": STATUS_LABELS.get(status, "Unknown"),
        "summary": summary,
        "started_at": started_at,
        "finished_at": finished_at,
        "artifact_count": 0,
        "artifact_types": [],
    }


def inject_import_stage(
    payload: dict[str, Any],
    *,
    status: str,
    summary: str = "",
    started_at: str = "",
    finished_at: str = "",
) -> dict[str, Any]:
    stage_view = build_import_stage_view(
        status=status,
        summary=summary,
        started_at=started_at,
        finished_at=finished_at,
    )
    updated = dict(payload)
    stages = [stage for stage in list(payload.get("stages") or []) if str(stage.get("stage") or "") != "import"]
    updated["stages"] = [stage_view, *stages]
    details = dict(payload.get("details") or {})
    details["import"] = {
        "status": status,
        "status_label": STATUS_LABELS.get(status, "Unknown"),
        "summary": summary,
        "cards": [
            {"label": "Status", "value": STATUS_LABELS.get(status, "Unknown")},
            {"label": "Started", "value": started_at or "-"},
            {"label": "Finished", "value": finished_at or "-"},
        ],
    }
    updated["details"] = details
    return updated


def decorate_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    run_payload = dict(updated.get("run") or {})
    repair_payload = dict(updated.get("repair") or {})
    stages = list(updated.get("stages") or [])
    recent_events = list(updated.get("recent_events") or [])
    repair_events = list(updated.get("repair_events") or [])

    story = _build_story_payload(
        run=run_payload,
        stages=stages,
        repair=repair_payload,
        recent_events=recent_events,
    )
    repair_story = _build_repair_story_payload(
        repair=repair_payload,
        recent_events=recent_events,
        repair_events=repair_events,
    )

    updated["story"] = story
    updated["repair_story"] = repair_story
    return updated


def discover_runs(*, generated_root: str | Path, site: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    root = Path(generated_root)
    if not root.exists():
        return []

    run_roots: list[Path] = []
    if site:
        site_root = root / site
        if site_root.exists():
            run_roots.extend(path for path in site_root.iterdir() if path.is_dir())
    else:
        for site_root in root.iterdir():
            if not site_root.is_dir():
                continue
            run_roots.extend(path for path in site_root.iterdir() if path.is_dir())

    run_roots.sort(key=_sort_key_for_run_root, reverse=True)
    items: list[dict[str, Any]] = []
    for run_root in run_roots[: max(1, int(limit))]:
        run_meta = _read_json(run_root / "run.json") or {}
        summary = _read_json(run_root / "views" / "run-summary.json") or {}
        events = _read_events(run_root)
        status = str(summary.get("status") or _derive_overall_status(events=events, process=None))
        items.append(
            {
                "run_id": str(run_meta.get("run_id") or run_root.name),
                "site": str(run_meta.get("site") or run_root.parent.name),
                "status": status,
                "status_label": STATUS_LABELS.get(status, "Unknown"),
                "run_root": str(run_root.resolve()),
                "latest_event_summary": str((events[-1] or {}).get("summary") or "") if events else "",
                "latest_event_timestamp": str((events[-1] or {}).get("timestamp") or "") if events else "",
            }
        )
    return items


def load_run_dashboard(*, run_root: str | Path, process: ProcessSnapshot | None = None) -> dict[str, Any]:
    root = Path(run_root)
    run_meta = _read_json(root / "run.json") or {}
    manifest = _read_json(root / "manifest.json") or {}
    summary = _read_json(root / "views" / "run-summary.json") or {}
    events = _read_events(root)

    analysis_bundle = _read_artifact_payload(root, "analysis", "analysis-bundle")
    analysis_snapshot = _read_artifact_payload(root, "analysis", "snapshot")
    planning_bundle = _read_artifact_payload(root, "planning", "planning-bundle")
    integration_plan = _read_artifact_payload(root, "planning", "integration-plan")
    host_edit_program = _read_artifact_payload(root, "compile", "host-edit-program")
    chatbot_edit_program = _read_artifact_payload(root, "compile", "chatbot-edit-program")
    compile_preflight = _read_artifact_payload(root, "compile", "compile-preflight")
    apply_result = _read_artifact_payload(root, "apply", "apply-result")
    replay_result = _read_artifact_payload(root, "export", "replay-result")
    validation_bundle = _read_artifact_payload(root, "validation", "validation-bundle")
    backend_runtime_state = _read_artifact_payload(root, "validation", "backend-runtime-state")
    widget_bundle_fetch = _read_artifact_payload(root, "validation", "widget-bundle-fetch")
    host_auth_bootstrap = _read_artifact_payload(root, "validation", "host-auth-bootstrap")
    chatbot_adapter_auth = _read_artifact_payload(root, "validation", "chatbot-adapter-auth")
    widget_order_e2e = _read_artifact_payload(root, "validation", "widget-order-e2e")
    repair_failure_bundle = _read_artifact_payload(root, "repair", "failure-bundle")
    repair_decision = _read_artifact_payload(root, "repair", "repair-decision")

    overall_status = str(summary.get("status") or _derive_overall_status(events=events, process=process))
    stages = _build_stage_views(root=root, events=events, process=process)
    validation_checks = list((validation_bundle or {}).get("checks") or [])
    repair = _build_repair_details(
        summary=summary,
        events=events,
        failure_bundle=repair_failure_bundle,
        repair_decision=repair_decision,
    )

    return {
        "run": {
            "run_id": str(run_meta.get("run_id") or root.name),
            "site": str(run_meta.get("site") or root.parent.name),
            "source_root": str(run_meta.get("source_root") or manifest.get("source_root") or ""),
            "engine": str(run_meta.get("engine") or ""),
            "status": overall_status,
            "status_label": STATUS_LABELS.get(overall_status, "Unknown"),
            "run_root": str(root.resolve()),
            "stopped_for_review": bool(summary.get("stopped_for_review") or False),
            "repair_attempt_count": int(summary.get("repair_attempt_count") or 0),
            "latest_failure_signature": str(summary.get("latest_failure_signature") or ""),
            "latest_rewind_to": str(summary.get("latest_rewind_to") or ""),
            "retrieval_status": dict(summary.get("retrieval_status") or {}),
            "enabled_retrieval_corpora": list(summary.get("enabled_retrieval_corpora") or []),
        },
        "process": {
            "running": bool(process.running) if process else False,
            "pid": None if process is None else process.pid,
            "command": [] if process is None or process.command is None else list(process.command),
            "log_path": None if process is None else process.log_path,
            "started_at": None if process is None else process.started_at,
            "finished_at": None if process is None else process.finished_at,
            "returncode": None if process is None else process.returncode,
            "preview_url": None if process is None else process.preview_url,
        },
        "stages": stages,
        "repair": repair,
        "recent_events": [_compact_event(event) for event in events[-14:]],
        "repair_events": [_compact_event(event) for event in events if str(event.get("stage")) == "repair"][-8:],
        "details": {
            "analysis": _build_analysis_details(analysis_snapshot=analysis_snapshot, analysis_bundle=analysis_bundle),
            "planning": _build_planning_details(plan=integration_plan, planning_bundle=planning_bundle),
            "compile": _build_compile_details(
                host_edit_program=host_edit_program,
                chatbot_edit_program=chatbot_edit_program,
                compile_preflight=compile_preflight,
            ),
            "apply": _build_apply_details(apply_result=apply_result),
            "export": _build_export_details(root=root, replay_result=replay_result),
            "validation": _build_validation_details(
                validation_bundle=validation_bundle,
                validation_checks=validation_checks,
                backend_runtime_state=backend_runtime_state,
                widget_bundle_fetch=widget_bundle_fetch,
                host_auth_bootstrap=host_auth_bootstrap,
                chatbot_adapter_auth=chatbot_adapter_auth,
                widget_order_e2e=widget_order_e2e,
            ),
        },
    }


def _sort_key_for_run_root(run_root: Path) -> float:
    candidates = [
        run_root / "views" / "run-summary.json",
        run_root / "events" / "events.jsonl",
        run_root / "run.json",
    ]
    existing = [path.stat().st_mtime for path in candidates if path.exists()]
    return max(existing) if existing else run_root.stat().st_mtime


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_events(run_root: Path) -> list[dict[str, Any]]:
    events_path = run_root / "events" / "events.jsonl"
    if not events_path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _read_artifact_payload(run_root: Path, stage: str, artifact_type: str) -> dict[str, Any] | None:
    artifact_dir = run_root / "artifacts" / STAGE_DIRECTORY_MAP[stage] / artifact_type
    latest_ref = _read_json(artifact_dir / "latest.json")
    if latest_ref is None:
        return None
    versioned_path = artifact_dir / str(latest_ref.get("path") or "")
    envelope = _read_json(versioned_path)
    if envelope is None:
        return None
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else None


def _build_stage_views(
    *,
    root: Path,
    events: list[dict[str, Any]],
    process: ProcessSnapshot | None,
) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for stage in STAGE_ORDER:
        stage_events = [event for event in events if str(event.get("stage")) == stage]
        relevant = [event for event in stage_events if _is_stage_status_event(event)]
        terminal_events = [event for event in relevant if _is_terminal_stage_event(event)]
        last_terminal_event = terminal_events[-1] if terminal_events else None
        last_event = relevant[-1] if relevant else None
        status = "pending"
        summary_source = last_terminal_event if last_terminal_event is not None else last_event
        summary = "" if summary_source is None else str(summary_source.get("summary") or "")
        if last_terminal_event is not None:
            event_type = str(last_terminal_event.get("event_type") or "")
            if event_type in {"stage_completed", "compile_preflight_completed"}:
                status = "completed"
            else:
                status = "failed"
        elif last_event is not None:
            event_type = str(last_event.get("event_type") or "")
            status = _resolve_incomplete_stage_status(process=process)
            if status == "failed":
                summary = _interrupted_stage_summary(stage=stage, event_type=event_type, fallback=summary)
        views.append(
            {
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "status": status,
                "status_label": STATUS_LABELS.get(status, "Unknown"),
                "summary": summary,
                "started_at": _first_timestamp(stage_events, "stage_started"),
                "finished_at": _last_finished_timestamp(stage_events),
                "artifact_count": _count_stage_artifacts(root=root, stage=stage),
                "artifact_types": _stage_artifact_types(root=root, stage=stage),
            }
        )
    return views


def _resolve_incomplete_stage_status(*, process: ProcessSnapshot | None) -> str:
    if process is None:
        return "running"
    if process.running:
        return "running"
    return "failed"


def _interrupted_stage_summary(*, stage: str, event_type: str, fallback: str) -> str:
    if stage == "compile" and event_type == "compile_preflight_started":
        return "compile finished, but compile preflight was interrupted before completion"
    if fallback:
        return f"{fallback} before the onboarding process exited"
    return f"{STAGE_LABELS.get(stage, stage.title())} stopped before completion"


def _is_stage_status_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    return event_type in {
        "stage_started",
        "stage_completed",
        "stage_failed",
        "stage_rerun_started",
        "compile_preflight_started",
        "compile_preflight_completed",
    }


def _is_terminal_stage_event(event: dict[str, Any]) -> bool:
    return str(event.get("event_type") or "") in {
        "stage_completed",
        "stage_failed",
        "compile_preflight_completed",
    }


def _first_timestamp(events: list[dict[str, Any]], event_type: str) -> str:
    for event in events:
        if str(event.get("event_type")) == event_type:
            return str(event.get("timestamp") or "")
    return ""


def _last_finished_timestamp(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if str(event.get("event_type") or "") in {"stage_completed", "stage_failed", "compile_preflight_completed"}:
            return str(event.get("timestamp") or "")
    return ""


def _count_stage_artifacts(*, root: Path, stage: str) -> int:
    stage_root = root / "artifacts" / STAGE_DIRECTORY_MAP[stage]
    if not stage_root.exists():
        return 0
    count = 0
    for index_path in stage_root.glob("*/index.json"):
        payload = _read_json(index_path) or {}
        count += len(payload.get("items") or [])
    return count


def _stage_artifact_types(*, root: Path, stage: str) -> list[str]:
    stage_root = root / "artifacts" / STAGE_DIRECTORY_MAP[stage]
    if not stage_root.exists():
        return []
    return sorted(path.name for path in stage_root.iterdir() if path.is_dir())


def _derive_overall_status(*, events: list[dict[str, Any]], process: ProcessSnapshot | None) -> str:
    if process is not None:
        if process.running:
            return "running"
        if process.returncode not in (None, 0):
            return "process_failed"

    for event in reversed(events):
        event_type = str(event.get("event_type") or "")
        stage = str(event.get("stage") or "")
        if stage == "repair" and event_type == "repair_stopped":
            return "failed_human_review"
        if stage == "validation" and event_type == "stage_completed":
            return "exported"
        if event_type == "stage_failed":
            return "failed"
    return "pending"


def _build_repair_details(
    *,
    summary: dict[str, Any] | None,
    events: list[dict[str, Any]],
    failure_bundle: dict[str, Any] | None,
    repair_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    run_summary = summary or {}
    bundle = failure_bundle or {}
    decision = repair_decision or {}
    latest_failed = _latest_event(events, event_type="stage_failed")
    latest_rewind = _latest_event(events, event_type="rewind_requested")
    latest_stop = _latest_event(events, event_type="repair_stopped", stage="repair")

    failed_stage = str(bundle.get("failed_stage") or (latest_failed or {}).get("stage") or "").strip()
    failure_signature = str(
        bundle.get("failure_signature")
        or (latest_failed or {}).get("failure_signature")
        or run_summary.get("latest_failure_signature")
        or ""
    ).strip()
    failure_summary = str(
        bundle.get("failure_summary")
        or ((latest_failed or {}).get("details") or {}).get("error")
        or (latest_failed or {}).get("summary")
        or ""
    ).strip()
    requested_rewind_to = str(
        decision.get("requested_rewind_to")
        or (latest_rewind or {}).get("requested_rewind_to")
        or ""
    ).strip()
    effective_rewind_to = str(
        decision.get("effective_rewind_to")
        or (latest_rewind or {}).get("effective_rewind_to")
        or run_summary.get("latest_rewind_to")
        or ""
    ).strip()
    diagnosis = str(decision.get("diagnosis") or "").strip()
    diagnosis_summary = _localize_stage_names_ko(
        _summarize_korean_text(diagnosis, max_sentences=2, max_chars=280)
    )
    stop_reason = str(
        decision.get("stop_reason")
        or ((latest_stop or {}).get("details") or {}).get("stop_reason")
        or ""
    ).strip()
    stop_reason_text = _stop_reason_text_ko(stop_reason)
    repeat_count = int(bundle.get("repeat_count") or 0)
    attempt_number = int(bundle.get("attempt_number") or 0)

    active = bool(
        failed_stage
        or failure_signature
        or failure_summary
        or diagnosis
        or requested_rewind_to
        or effective_rewind_to
        or stop_reason
    )
    if not active:
        return {
            "active": False,
            "status": "pending",
            "status_label": "",
            "failed_stage": "",
            "failed_stage_label": "",
            "failure_signature": "",
            "failure_summary": "",
            "requested_rewind_to": "",
            "effective_rewind_to": "",
            "effective_rewind_label": "",
            "problem_explanation": "",
            "diagnosis_summary": "",
            "current_action": "",
            "stop_reason": "",
            "stop_reason_text": "",
            "repeat_count": 0,
            "attempt_number": 0,
        }

    if stop_reason or bool(run_summary.get("stopped_for_review")):
        status = "failed"
        status_label = "자동 복구 중단"
    elif effective_rewind_to:
        status = "running"
        status_label = f"{_stage_label_ko(effective_rewind_to)} 단계로 되감기"
    else:
        status = "running"
        status_label = "문제 원인 분석 중"

    current_action = ""
    if stop_reason_text:
        current_action = stop_reason_text
    elif effective_rewind_to:
        current_action = f"{_stage_label_ko(effective_rewind_to)} 단계부터 다시 실행하도록 결정했습니다."
    elif requested_rewind_to:
        current_action = f"{_stage_label_ko(requested_rewind_to)} 단계 재실행 여부를 판단 중입니다."

    return {
        "active": True,
        "status": status,
        "status_label": status_label,
        "failed_stage": failed_stage,
        "failed_stage_label": _stage_label_ko(failed_stage),
        "failure_signature": failure_signature,
        "failure_summary": failure_summary,
        "requested_rewind_to": requested_rewind_to,
        "effective_rewind_to": effective_rewind_to,
        "effective_rewind_label": _stage_label_ko(effective_rewind_to),
        "problem_explanation": _repair_problem_explanation_ko(
            failed_stage=failed_stage,
            failure_summary=failure_summary,
            effective_rewind_to=effective_rewind_to,
            stop_reason=stop_reason,
        ),
        "diagnosis_summary": diagnosis_summary,
        "current_action": current_action,
        "stop_reason": stop_reason,
        "stop_reason_text": stop_reason_text,
        "repeat_count": repeat_count,
        "attempt_number": attempt_number,
    }


def _latest_event(
    events: list[dict[str, Any]],
    *,
    event_type: str,
    stage: str | None = None,
) -> dict[str, Any] | None:
    for event in reversed(events):
        if str(event.get("event_type") or "") != event_type:
            continue
        if stage is not None and str(event.get("stage") or "") != stage:
            continue
        return event
    return None


def _stage_label_ko(stage: str) -> str:
    return STAGE_LABELS_KO.get(str(stage or "").strip(), str(stage or "").strip() or "-")


def _stop_reason_text_ko(stop_reason: str) -> str:
    normalized = str(stop_reason or "").strip()
    if not normalized:
        return ""
    if normalized == "repeated_failure_signature":
        return "같은 문제가 반복되어 자동 복구를 멈추고 확인이 필요한 상태입니다."
    if normalized == "repair_llm_unavailable":
        return "복구 판단에 필요한 진단 응답을 만들지 못해 자동 복구를 멈췄습니다."
    return f"자동 복구가 중단되었습니다: {normalized}"


def _repair_problem_explanation_ko(
    *,
    failed_stage: str,
    failure_summary: str,
    effective_rewind_to: str,
    stop_reason: str,
) -> str:
    stage_label = _stage_label_ko(failed_stage)
    rewind_label = _stage_label_ko(effective_rewind_to)
    parts: list[str] = []
    if failure_summary:
        parts.append(f"{stage_label} 단계에서 {failure_summary} 문제가 발생했습니다.")
    elif failed_stage:
        parts.append(f"{stage_label} 단계에서 문제가 발생했습니다.")
    if effective_rewind_to:
        parts.append(f"시스템은 {rewind_label} 단계로 되감아 다시 확인하려고 합니다.")
    if stop_reason:
        parts.append("현재는 자동 복구를 멈추고 사용자의 확인이 필요한 상태입니다.")
    return " ".join(part.strip() for part in parts if part.strip())


def _summarize_korean_text(text: str, *, max_sentences: int = 2, max_chars: int = 280) -> str:
    source = str(text or "").strip()
    if not source:
        return ""
    chunks = [part.strip() for part in source.replace("\n", " ").split(". ") if part.strip()]
    if chunks:
        summary = ". ".join(chunks[:max_sentences]).strip()
        if not summary.endswith("."):
            summary += "."
    else:
        summary = source
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "…"


def _localize_stage_names_ko(text: str) -> str:
    localized = str(text or "")
    replacements = {
        "Analysis": "분석",
        "Planning": "계획",
        "Compile": "컴파일",
        "Apply": "적용",
        "Export": "내보내기",
        "Validation": "검증",
    }
    for english, korean in replacements.items():
        localized = localized.replace(english, korean)
    return localized


def _build_analysis_details(*, analysis_snapshot: dict[str, Any] | None, analysis_bundle: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = analysis_snapshot or {}
    bundle = analysis_bundle or {}
    repo_profile = snapshot.get("repo_profile") or {}
    framework_profile = bundle.get("framework_profile") or {}
    domain = snapshot.get("domain_integration") or {}
    backend_seams = snapshot.get("backend_seams") or {}
    frontend_seams = snapshot.get("frontend_seams") or {}

    candidates = []
    for group_name, label in [
        ("route_registration_points", "Backend route"),
        ("auth_source_candidates", "Auth source"),
        ("widget_mount_candidates", "Widget mount"),
        ("api_client_candidates", "API client"),
    ]:
        for item in (backend_seams.get(group_name) or frontend_seams.get(group_name) or [])[:2]:
            path = str(item.get("path") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if path:
                candidates.append({"label": label, "path": path, "reason": reason})

    highlights = [
        entry
        for entry in [
            _highlight("Login endpoint", domain.get("login_endpoint")),
            _highlight("Auth validation", domain.get("auth_validation_endpoint")),
            _highlight("Current user", domain.get("current_user_endpoint")),
            _highlight("Order list", domain.get("order_list_endpoint")),
            _highlight("Order action", domain.get("order_action_endpoint")),
        ]
        if entry is not None
    ]

    return {
        "cards": [
            _card("Backend", repo_profile.get("backend_framework") or framework_profile.get("backend_framework"), ""),
            _card("Frontend", repo_profile.get("frontend_framework") or framework_profile.get("frontend_framework"), ""),
            _card("Auth style", repo_profile.get("auth_style") or framework_profile.get("auth_style"), ""),
            _card("Unresolved", len(bundle.get("unresolved_ambiguities") or []), "ambiguities left"),
        ],
        "highlights": highlights,
        "candidates": candidates,
        "confidence_notes": [str(item) for item in (framework_profile.get("confidence_notes") or [])[:5]],
    }


def _build_planning_details(*, plan: dict[str, Any] | None, planning_bundle: dict[str, Any] | None) -> dict[str, Any]:
    integration_plan = plan or {}
    planning = planning_bundle or {}
    host_backend = integration_plan.get("host_backend") or {}
    host_frontend = integration_plan.get("host_frontend") or {}
    chatbot_bridge = integration_plan.get("chatbot_bridge") or {}
    target_bindings = planning.get("target_bindings") or []
    validation_plan = planning.get("validation_plan") or []
    risks = planning.get("risk_register") or []

    return {
        "cards": [
            _card("Mount target", host_frontend.get("mount_target"), host_frontend.get("mount_strategy")),
            _card("API client", host_frontend.get("api_client_target"), host_frontend.get("api_strategy")),
            _card("Auth contract", host_backend.get("chat_auth_contract_path"), host_backend.get("auth_handler_source")),
            _card("Adapter package", chatbot_bridge.get("adapter_package"), chatbot_bridge.get("site_key")),
        ],
        "target_bindings": [
            {
                "capability": str(item.get("capability") or ""),
                "target_path": str(item.get("target_path") or ""),
                "reason": str(item.get("selection_reason") or ""),
            }
            for item in target_bindings[:8]
        ],
        "validation_plan": [
            {
                "name": str(item.get("name") or ""),
                "target": str(item.get("target") or ""),
                "success_signal": str(item.get("success_signal") or ""),
            }
            for item in validation_plan[:8]
        ],
        "risks": [
            {
                "summary": str(item.get("summary") or ""),
                "severity": str(item.get("severity") or "medium"),
                "mitigations": [str(value) for value in (item.get("mitigations") or [])[:3]],
            }
            for item in risks[:4]
        ],
    }


def _build_compile_details(
    *,
    host_edit_program: dict[str, Any] | None,
    chatbot_edit_program: dict[str, Any] | None,
    compile_preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    host_program = host_edit_program or {}
    chatbot_program = chatbot_edit_program or {}

    host_targets = _collect_host_targets(host_program)
    chatbot_targets = _collect_chatbot_targets(chatbot_program)
    host_operations = _collect_operations(host_program)
    chatbot_operations = _collect_operations(chatbot_program)

    return {
        "cards": [
            _card("Host files", len(host_targets), "files touched"),
            _card("Chatbot files", len(chatbot_targets), "files touched"),
            _card("Host edits", len(host_operations), "operations"),
            _card("Chatbot edits", len(chatbot_operations), "operations"),
        ],
        "host_targets": host_targets[:10],
        "chatbot_targets": chatbot_targets[:10],
        "operation_mix": _operation_mix(host_operations + chatbot_operations),
        "preflight": {
            "passed": bool((compile_preflight or {}).get("passed")),
            "summary": str((compile_preflight or {}).get("failure_summary") or ""),
            "scan_paths": [str(item) for item in ((compile_preflight or {}).get("scan_paths") or [])[:8]],
        },
    }


def _build_apply_details(*, apply_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = apply_result or {}
    return {
        "cards": [
            _card("Workspace", _tail_path(payload.get("workspace_path")), "runtime workspace"),
            _card("Host workspace", _tail_path(payload.get("host_workspace_path")), "host copy"),
            _card("Chatbot workspace", _tail_path(payload.get("chatbot_workspace_path")), "chatbot copy"),
            _card("Applied files", len(payload.get("applied_files") or []), "total"),
        ],
        "paths": [
            entry
            for entry in [
                _highlight("Runtime workspace", payload.get("workspace_path")),
                _highlight("Host workspace", payload.get("host_workspace_path")),
                _highlight("Chatbot workspace", payload.get("chatbot_workspace_path")),
            ]
            if entry is not None
        ],
        "workspace_paths": {
            "runtime_workspace": str(payload.get("workspace_path") or "").strip(),
            "host_workspace": str(payload.get("host_workspace_path") or "").strip(),
            "chatbot_workspace": str(payload.get("chatbot_workspace_path") or "").strip(),
        },
        "applied_files": [str(item) for item in (payload.get("applied_files") or [])[:16]],
    }


def _build_export_details(*, root: Path, replay_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = replay_result or {}
    host_patch_ref = _read_json(root / "artifacts" / STAGE_DIRECTORY_MAP["export"] / "host-approved.patch" / "latest.json") or {}
    chatbot_patch_ref = _read_json(root / "artifacts" / STAGE_DIRECTORY_MAP["export"] / "chatbot-approved.patch" / "latest.json") or {}

    host_patch_path = ""
    if host_patch_ref:
        host_patch_path = str((root / "artifacts" / STAGE_DIRECTORY_MAP["export"] / "host-approved.patch" / str(host_patch_ref.get("path") or "")).resolve())
    chatbot_patch_path = ""
    if chatbot_patch_ref:
        chatbot_patch_path = str((root / "artifacts" / STAGE_DIRECTORY_MAP["export"] / "chatbot-approved.patch" / str(chatbot_patch_ref.get("path") or "")).resolve())

    return {
        "cards": [
            _card("Replay apply", "Passed" if payload.get("passed") else "Pending", ""),
            _card("Target match", "Passed" if payload.get("target_match_passed") else "Failed", ""),
            _card("Static validation", "Passed" if payload.get("static_validation_passed") else "Failed", ""),
            _card("Patch artifacts", len(payload.get("applied_patch_artifacts") or []), "applied"),
        ],
        "paths": [
            entry
            for entry in [
                _highlight("Host patch", host_patch_path),
                _highlight("Chatbot patch", chatbot_patch_path),
                _highlight("Replay workspace", payload.get("replay_workspace_path")),
            ]
            if entry is not None
        ],
        "failure_summary": str(payload.get("static_validation_summary") or ""),
    }


def _build_validation_details(
    *,
    validation_bundle: dict[str, Any] | None,
    validation_checks: list[dict[str, Any]],
    backend_runtime_state: dict[str, Any] | None,
    widget_bundle_fetch: dict[str, Any] | None,
    host_auth_bootstrap: dict[str, Any] | None,
    chatbot_adapter_auth: dict[str, Any] | None,
    widget_order_e2e: dict[str, Any] | None,
) -> dict[str, Any]:
    bundle = validation_bundle or {}
    runtime_state = backend_runtime_state or {}
    widget_fetch = widget_bundle_fetch or {}
    host_bootstrap = host_auth_bootstrap or {}
    adapter_auth = chatbot_adapter_auth or {}
    widget_e2e = widget_order_e2e or {}

    proofs = [
        entry
        for entry in [
            _highlight("Readiness URL", runtime_state.get("readiness_url")),
            _highlight("Widget bundle", widget_fetch.get("target_url")),
            _highlight("Login URL", host_bootstrap.get("login_url")),
            _highlight("Bootstrap URL", host_bootstrap.get("bootstrap_url")),
        ]
        if entry is not None
    ]

    covered_flows = [str(item) for item in (widget_e2e.get("covered_flows") or [])]
    flow_reports = widget_e2e.get("flow_reports") or {}

    return {
        "passed": bool(bundle.get("passed")),
        "cards": [
            _card("Validation", "Passed" if bundle.get("passed") else "Failed", bundle.get("failure_summary") or ""),
            _card("Backend runtime", "Ready" if runtime_state.get("passed") else "Blocked", runtime_state.get("framework") or ""),
            _card("Widget bundle", "Fetched" if widget_fetch.get("passed") else "Missing", ""),
            _card("Widget E2E", "Passed" if widget_e2e.get("passed") else "Failed", ""),
        ],
        "checks": [
            {
                "name": str(item.get("name") or ""),
                "passed": bool(item.get("passed")),
                "summary": str(item.get("summary") or ""),
            }
            for item in validation_checks
        ],
        "proofs": proofs,
        "covered_flows": covered_flows,
        "flow_reports": [
            {
                "name": name,
                "passed": bool((report or {}).get("passed")),
                "summary": str((report or {}).get("failure_summary") or "flow passed"),
            }
            for name, report in flow_reports.items()
        ],
        "sampled_order_id": str(widget_e2e.get("sampled_order_id") or ""),
        "validated_user_id": str((adapter_auth.get("validated_user") or {}).get("id") or ""),
    }


def _collect_host_targets(program: dict[str, Any]) -> list[str]:
    targets: set[str] = set()
    for bundle_key in ["backend_wiring_bundles", "frontend_mount_bundles", "frontend_api_bundles"]:
        for bundle in program.get(bundle_key) or []:
            if isinstance(bundle.get("target_path"), str):
                targets.add(bundle["target_path"])
            for path in bundle.get("target_paths") or []:
                targets.add(str(path))
            for operation in bundle.get("operations") or []:
                if operation.get("path"):
                    targets.add(str(operation["path"]))
            for artifact in bundle.get("supporting_files") or []:
                if artifact.get("path"):
                    targets.add(str(artifact["path"]))
    for artifact in program.get("supporting_artifact_bundles") or []:
        if artifact.get("path"):
            targets.add(str(artifact["path"]))
    return sorted(targets)


def _collect_chatbot_targets(program: dict[str, Any]) -> list[str]:
    targets: set[str] = set()
    for bundle in program.get("bridge_bundles") or []:
        for path in bundle.get("target_paths") or []:
            targets.add(str(path))
        for operation in bundle.get("operations") or []:
            if operation.get("path"):
                targets.add(str(operation["path"]))
        for artifact in bundle.get("supporting_files") or []:
            if artifact.get("path"):
                targets.add(str(artifact["path"]))
    for artifact in program.get("supporting_artifact_bundles") or []:
        if artifact.get("path"):
            targets.add(str(artifact["path"]))
    return sorted(targets)


def _collect_operations(program: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for key, value in program.items():
        if not isinstance(value, list):
            continue
        for bundle in value:
            if isinstance(bundle, dict):
                operations.extend(bundle.get("operations") or [])
    return [operation for operation in operations if isinstance(operation, dict)]


def _operation_mix(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for operation in operations:
        name = str(operation.get("operation") or "unknown")
        counts[name] = counts.get(name, 0) + 1
    return [{"operation": key, "count": value} for key, value in sorted(counts.items())]


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": str(event.get("timestamp") or ""),
        "stage": str(event.get("stage") or ""),
        "phase": str(event.get("phase") or ""),
        "event_type": str(event.get("event_type") or ""),
        "summary": str(event.get("summary") or ""),
        "severity": str(event.get("severity") or "info"),
    }


def _build_story_payload(
    *,
    run: dict[str, Any],
    stages: list[dict[str, Any]],
    repair: dict[str, Any],
    recent_events: list[dict[str, Any]],
) -> dict[str, Any]:
    current_stage = _select_story_current_stage(stages)
    current_label = str(current_stage.get("label") or current_stage.get("stage") or "-")
    current_status = str(current_stage.get("status") or "pending")
    repair_active = bool(repair.get("active"))
    failed_stage = str(repair.get("failed_stage") or "").strip()
    rewind_to = str(repair.get("effective_rewind_to") or repair.get("requested_rewind_to") or "").strip()
    focus_stage = current_stage
    if repair_active and rewind_to:
        focus_stage = next((stage for stage in stages if str(stage.get("stage") or "") == rewind_to), current_stage)

    story_steps = []
    for stage in stages:
        stage_key = str(stage.get("stage") or "")
        emphasis = "default"
        if stage_key == str(current_stage.get("stage") or ""):
            emphasis = "current"
        elif str(stage.get("status") or "") == "failed":
            emphasis = "failed"
        elif repair_active and rewind_to and stage_key == rewind_to:
            emphasis = "rewind"
        story_steps.append(
            {
                "stage": stage_key,
                "label": str(stage.get("label") or stage_key),
                "status": str(stage.get("status") or "pending"),
                "status_label": str(stage.get("status_label") or STATUS_LABELS.get(str(stage.get("status") or "pending"), "Unknown")),
                "emphasis": emphasis,
            }
        )

    headline = f"현재 {current_label} 단계가 진행 중입니다."
    summary = str(current_stage.get("summary") or "").strip()
    if current_status == "failed":
        headline = f"{current_label} 단계에서 실행이 중단되었습니다."
    elif current_status == "completed":
        headline = "온보딩 흐름이 완료되었습니다."

    if repair_active:
        failed_label = str(repair.get("failed_stage_label") or _stage_label_ko(failed_stage) or failed_stage or "")
        rewind_label = str(repair.get("effective_rewind_label") or _stage_label_ko(rewind_to) or rewind_to or "")
        if current_status == "running":
            headline = f"현재 {current_label} 단계가 다시 진행 중입니다."
        if failed_label and rewind_label:
            summary = f"{failed_label} 단계 실패 이후 {rewind_label} 단계로 되감아 다시 확인하고 있습니다."
        elif str(repair.get("problem_explanation") or "").strip():
            summary = str(repair.get("problem_explanation") or "").strip()
        if str(repair.get("current_action") or "").strip():
            summary = str(repair.get("current_action") or "").strip()

    if not summary:
        if recent_events:
            summary = str(recent_events[-1].get("summary") or "").strip()
        if not summary:
            summary = "현재 실행 흐름을 준비 중입니다."

    retrieval_story = _build_retrieval_story(run=run, repair=repair)

    return {
        "headline": headline,
        "summary": summary,
        "steps": story_steps,
        "current_stage": {
            "stage": str(current_stage.get("stage") or ""),
            "label": current_label,
            "status": current_status,
            "status_label": str(current_stage.get("status_label") or STATUS_LABELS.get(current_status, "Unknown")),
        },
        "focus_stage": {
            "stage": str(focus_stage.get("stage") or ""),
            "label": str(focus_stage.get("label") or focus_stage.get("stage") or ""),
            "status": str(focus_stage.get("status") or "pending"),
            "status_label": str(
                focus_stage.get("status_label")
                or STATUS_LABELS.get(str(focus_stage.get("status") or "pending"), "Unknown")
            ),
        },
        "retrieval": retrieval_story,
    }


def _build_repair_story_payload(
    *,
    repair: dict[str, Any],
    recent_events: list[dict[str, Any]],
    repair_events: list[dict[str, Any]],
) -> dict[str, Any]:
    if not bool(repair.get("active")):
        return {
            "active": False,
            "headline": "",
            "summary": "",
            "steps": [],
            "failed_stage": "",
            "rewind_to": "",
        }

    failed_stage = str(repair.get("failed_stage") or "").strip()
    failed_label = str(repair.get("failed_stage_label") or _stage_label_ko(failed_stage) or failed_stage or "문제 단계").strip()
    rewind_to = str(repair.get("effective_rewind_to") or repair.get("requested_rewind_to") or "").strip()
    rewind_label = str(repair.get("effective_rewind_label") or _stage_label_ko(rewind_to) or rewind_to or "이전 단계").strip()
    stop_reason_text = str(repair.get("stop_reason_text") or "").strip()

    failure_event = _find_event(recent_events, event_type="stage_failed", stage=failed_stage)
    diagnosis_event = _find_event(repair_events, event_type="repair_diagnosis_started")
    decision_event = _find_event(repair_events, event_type="repair_decision_emitted")
    rewind_event = _find_event(repair_events, event_type="rewind_requested")
    rerun_event = _find_event(recent_events, event_type="stage_rerun_started", stage=rewind_to)
    stopped_event = _find_event(repair_events, event_type="repair_stopped", stage="repair")

    diagnosis_status = "completed" if str(repair.get("diagnosis_summary") or "").strip() or diagnosis_event else "running"
    rewind_status = "failed" if stop_reason_text else ("completed" if rewind_to else "running")
    rerun_status = "failed" if stop_reason_text else ("running" if rerun_event or rewind_to else "pending")
    rerun_label = "사용자 확인 대기" if stop_reason_text else f"{rewind_label} 재실행 시작"

    return {
        "active": True,
        "headline": "Repair Rewind",
        "summary": str(repair.get("problem_explanation") or repair.get("current_action") or "").strip(),
        "status_label": str(repair.get("status_label") or "").strip(),
        "steps": [
            {
                "kind": "failure",
                "label": f"{failed_label} 실패 감지",
                "status": "completed",
                "timestamp": str((failure_event or {}).get("timestamp") or ""),
            },
            {
                "kind": "diagnosis",
                "label": "원인 진단 완료" if diagnosis_status == "completed" else "원인 진단 중",
                "status": diagnosis_status,
                "timestamp": str((decision_event or diagnosis_event or {}).get("timestamp") or ""),
            },
            {
                "kind": "rewind",
                "label": "자동 복구 중단" if stop_reason_text else f"{rewind_label}로 되감기 결정",
                "status": rewind_status,
                "timestamp": str((stopped_event or rewind_event or decision_event or {}).get("timestamp") or ""),
            },
            {
                "kind": "rerun",
                "label": rerun_label,
                "status": rerun_status,
                "timestamp": str((rerun_event or stopped_event or {}).get("timestamp") or ""),
            },
        ],
        "failed_stage": failed_stage,
        "failed_stage_label": failed_label,
        "rewind_to": rewind_to,
        "rewind_to_label": rewind_label,
        "problem": str(repair.get("problem_explanation") or repair.get("failure_summary") or "").strip(),
        "diagnosis": str(repair.get("diagnosis_summary") or "").strip(),
        "current_action": str(repair.get("current_action") or stop_reason_text or "").strip(),
    }


def _build_retrieval_story(*, run: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    retrieval_status = dict(run.get("retrieval_status") or {})
    enabled = list(run.get("enabled_retrieval_corpora") or [])
    corpora = list(dict.fromkeys(enabled + list(retrieval_status.keys())))
    if not corpora:
        return {
            "active": False,
            "headline": "",
            "summary": "",
            "items": [],
            "rewind_note": "",
        }

    items = []
    ready_count = 0
    for corpus in corpora:
        payload = dict(retrieval_status.get(corpus) or {})
        status = _retrieval_chip_status(payload)
        if status == "ready":
            ready_count += 1
        items.append(
            {
                "corpus": corpus,
                "label": _corpus_label(corpus),
                "status": status,
                "status_label": _retrieval_status_label(status),
                "documents_indexed": int(payload.get("documents_indexed") or 0),
            }
        )

    summary = "Retrieval 준비 대기 중입니다."
    if all(item["status"] in {"ready", "skipped"} for item in items):
        summary = "Retrieval 준비가 완료되었습니다."
    elif any(item["status"] == "indexing" for item in items):
        summary = f"{len(items)}개 corpus 중 {ready_count}개 준비됨. Validation 전에 retrieval 사용 가능 상태를 맞추는 중입니다."
    elif any(item["status"] == "failed" for item in items):
        summary = "일부 retrieval 준비가 실패했습니다."

    rewind_note = ""
    rewind_to = str(repair.get("effective_rewind_to") or "").strip()
    if rewind_to and rewind_to in {"analysis", "planning", "compile", "apply", "export"}:
        rewind_note = "되감기로 인해 retrieval 준비도 다시 수행될 수 있습니다."

    return {
        "active": True,
        "headline": "Retrieval Ready",
        "summary": summary,
        "items": items,
        "rewind_note": rewind_note,
    }


def _select_story_current_stage(stages: list[dict[str, Any]]) -> dict[str, Any]:
    for stage in stages:
        if str(stage.get("status") or "") == "running":
            return stage
    for stage in reversed(stages):
        if str(stage.get("status") or "") == "failed":
            return stage
    for stage in reversed(stages):
        if str(stage.get("status") or "") == "completed":
            return stage
    return stages[0] if stages else {"stage": "", "label": "", "status": "pending", "status_label": "Waiting"}


def _find_event(
    events: list[dict[str, Any]],
    *,
    event_type: str,
    stage: str | None = None,
) -> dict[str, Any] | None:
    for event in reversed(events):
        if str(event.get("event_type") or "") != event_type:
            continue
        if stage is not None and str(event.get("stage") or "") != stage:
            continue
        return event
    return None


def _corpus_label(corpus: str) -> str:
    return {
        "faq": "FAQ",
        "policy": "Policy",
        "discovery_image": "Discovery Image",
    }.get(str(corpus or "").strip(), str(corpus or "").replace("_", " ").title())


def _retrieval_chip_status(payload: dict[str, Any]) -> str:
    raw_status = str(payload.get("status") or "").strip()
    if raw_status == "completed" and bool(payload.get("smoke_passed", True)):
        return "ready"
    if raw_status in {"running", "pending", "starting"}:
        return "indexing"
    if raw_status in {"failed", "cancelled"}:
        return "failed"
    if raw_status in {"skipped"}:
        return "skipped"
    if not raw_status:
        return "queued"
    return "queued"


def _retrieval_status_label(status: str) -> str:
    return {
        "ready": "Ready",
        "indexing": "Indexing",
        "queued": "Queued",
        "skipped": "Skipped",
        "failed": "Failed",
    }.get(str(status or ""), "Queued")


def _card(label: str, value: Any, caption: Any) -> dict[str, str]:
    return {
        "label": str(label or "").strip(),
        "value": str(value or "").strip() or "-",
        "caption": str(caption or "").strip(),
    }


def _highlight(label: str, value: Any) -> dict[str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    return {"label": label, "value": text}


def _tail_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    path = Path(text)
    parts = path.parts[-3:]
    return str(Path(*parts))
