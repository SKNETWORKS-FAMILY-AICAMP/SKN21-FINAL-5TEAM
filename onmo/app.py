from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, TextIO

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from onmo.dashboard import (
    ProcessSnapshot,
    STAGE_LABELS,
    STAGE_ORDER,
    STATUS_LABELS,
    discover_runs,
    load_run_dashboard,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "onmo" / "static"
DEFAULT_GENERATED_ROOT = ROOT / "generated-v2"
DEFAULT_RUNTIME_ROOT = ROOT / "runtime-v2"
DEFAULT_GENERATED_ROOT_ARG = "generated-v2"
DEFAULT_RUNTIME_ROOT_ARG = "runtime-v2"
DEFAULT_PREVIEW_URL = "http://127.0.0.1:3000/bilyeo/"
DEMO_SERVICE_NAMES = ("chatbot", "backend", "frontend")
SERVICE_STATUS_LABELS = {
    "pending": "Waiting",
    "starting": "Starting",
    "ready": "Ready",
    "failed": "Failed",
    "blocked": "Blocked",
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _resolve_repo_path(value: str, *, default: Path | None = None) -> Path:
    raw = str(value or "").strip()
    if not raw:
        if default is None:
            raise HTTPException(status_code=400, detail="Path value is required")
        return default
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _subprocess_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def _onmo_reload_enabled() -> bool:
    raw = str(os.environ.get("ONMO_RELOAD") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _build_child_env(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    # Demo/onboarding child processes should not emit LangSmith traces from the repo .env.
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    env["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"
    # Force UTF-8 inside child Python processes so nested subprocess text decoding
    # does not fall back to the Windows cp949 locale and break on UTF-8 output.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = _augment_path_for_export_tools(env.get("PATH", ""))
    if extra:
        env.update(extra)
    return env


def _augment_path_for_export_tools(path_value: str) -> str:
    entries = [item for item in str(path_value or "").split(os.pathsep) if item]
    lowered = {item.lower() for item in entries}

    candidates: list[Path] = []
    git_executable = shutil.which("git")
    if git_executable:
        git_root = Path(git_executable).resolve().parents[1]
        candidates.extend(
            [
                git_root / "usr" / "bin",
                git_root / "bin",
                git_root / "cmd",
            ]
        )

    if os.name == "nt":
        candidates.extend(
            [
                Path("C:/Program Files/Git/usr/bin"),
                Path("C:/Program Files/Git/bin"),
                Path("C:/Program Files/Git/cmd"),
            ]
        )

    for candidate in candidates:
        candidate_text = str(candidate)
        if not candidate.exists():
            continue
        if candidate_text.lower() in lowered:
            continue
        entries.insert(0, candidate_text)
        lowered.add(candidate_text.lower())

    return os.pathsep.join(entries)


def _close_log_handle(handle: TextIO) -> None:
    if not handle.closed:
        handle.close()


@dataclass(slots=True)
class RunProcessRecord:
    site: str
    run_id: str
    generated_root: str
    runtime_root: str
    source_root: str
    preview_url: str | None
    command: list[str]
    process: subprocess.Popen[str]
    log_path: Path
    log_handle: TextIO
    started_at: str
    finished_at: str | None = None
    returncode: int | None = None


@dataclass(slots=True)
class ServiceLaunchSpec:
    service_name: str
    label: str
    working_directory: Path
    command: list[str]
    url: str
    healthcheck_url: str | None = None
    healthcheck_port: int | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ServiceProcessRecord:
    site: str
    run_id: str
    service_name: str
    label: str
    working_directory: str
    command: list[str]
    process: subprocess.Popen[str]
    log_path: Path
    log_handle: TextIO
    started_at: str
    url: str
    healthcheck_url: str | None = None
    healthcheck_port: int | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)
    finished_at: str | None = None
    returncode: int | None = None


class StartRunRequest(BaseModel):
    site: str = Field(..., min_length=1)
    source_root: str = Field(..., min_length=1)
    generated_root: str = Field(default=DEFAULT_GENERATED_ROOT_ARG)
    runtime_root: str = Field(default=DEFAULT_RUNTIME_ROOT_ARG)
    run_id: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    chatbot_server_base_url: str | None = None
    preview_url: str | None = DEFAULT_PREVIEW_URL
    smoke_username: str | None = None
    smoke_email: str | None = None
    smoke_password: str | None = None

    model_config = ConfigDict(extra="ignore")


app = FastAPI(
    title="ONMO Demo Control",
    version="0.1.0",
    description="Onboarding motion room for demo recordings.",
)
app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

_REGISTRY_LOCK = Lock()
_RUN_REGISTRY: dict[str, RunProcessRecord] = {}
_SERVICE_REGISTRY: dict[str, ServiceProcessRecord] = {}


def _sync_record(record: RunProcessRecord) -> RunProcessRecord:
    if record.returncode is not None:
        return record
    polled = record.process.poll()
    if polled is None:
        return record
    record.returncode = polled
    record.finished_at = _utcnow()
    _close_log_handle(record.log_handle)
    return record


def _terminate_run(record: RunProcessRecord) -> None:
    synced = _sync_record(record)
    if synced.returncode is None:
        synced.process.terminate()
        try:
            synced.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            synced.process.kill()
            synced.process.wait(timeout=5)
        synced.returncode = synced.process.returncode
        synced.finished_at = _utcnow()
    _close_log_handle(synced.log_handle)


def _sync_service_record(record: ServiceProcessRecord) -> ServiceProcessRecord:
    if record.returncode is not None:
        return record
    polled = record.process.poll()
    if polled is None:
        return record
    record.returncode = polled
    record.finished_at = _utcnow()
    _close_log_handle(record.log_handle)
    return record


def _snapshot_from_record(record: RunProcessRecord | None) -> ProcessSnapshot | None:
    if record is None:
        return None
    synced = _sync_record(record)
    return ProcessSnapshot(
        running=synced.returncode is None,
        pid=synced.process.pid,
        command=list(synced.command),
        log_path=str(synced.log_path.resolve()),
        started_at=synced.started_at,
        finished_at=synced.finished_at,
        returncode=synced.returncode,
        preview_url=synced.preview_url,
    )


def _lookup_record(site: str, run_id: str) -> RunProcessRecord | None:
    key = f"{site}:{run_id}"
    with _REGISTRY_LOCK:
        record = _RUN_REGISTRY.get(key)
        if record is None:
            return None
        return _sync_record(record)


def _remove_run_tree(*, root: Path, site: str, run_id: str) -> None:
    site_root = (root / site).resolve()
    run_root = (site_root / run_id).resolve()
    if site_root not in run_root.parents:
        raise HTTPException(status_code=400, detail=f"Unsafe run root computed: {run_root}")
    if run_root.exists():
        shutil.rmtree(run_root)


def _clear_previous_run_state(
    *,
    site: str,
    run_id: str,
    generated_root: Path,
    runtime_root: Path,
) -> None:
    key = f"{site}:{run_id}"
    with _REGISTRY_LOCK:
        existing = _RUN_REGISTRY.get(key)
        if existing is not None:
            synced = _sync_record(existing)
            if synced.returncode is None:
                raise HTTPException(status_code=409, detail="Run already in progress")
            _RUN_REGISTRY.pop(key, None)

    _remove_run_tree(root=generated_root, site=site, run_id=run_id)
    _remove_run_tree(root=runtime_root, site=site, run_id=run_id)


def _clear_site_services(site: str) -> None:
    prefix = f"{site}:"
    with _REGISTRY_LOCK:
        keys = [key for key in _SERVICE_REGISTRY if key.startswith(prefix)]
        for key in keys:
            record = _SERVICE_REGISTRY.pop(key)
            _terminate_service(record)


def _project_options() -> list[dict[str, str]]:
    presets = [
        {
            "site": "bilyeo",
            "source_root": "bilyeo",
            "generated_root": DEFAULT_GENERATED_ROOT_ARG,
            "runtime_root": DEFAULT_RUNTIME_ROOT_ARG,
            "run_id": "bilyeo-v2-repair-015",
            "preview_url": DEFAULT_PREVIEW_URL,
        },
    ]
    items: list[dict[str, str]] = []
    for preset in presets:
        project_root = ROOT / preset["source_root"]
        if not project_root.exists():
            continue
        items.append(dict(preset))
    return items


def _build_pending_run_dashboard(
    *,
    site: str,
    run_id: str,
    run_root: Path,
    process: ProcessSnapshot | None,
) -> dict[str, Any]:
    process_status = "running"
    if process is None:
        process_status = "pending"
    elif process.returncode not in (None, 0):
        process_status = "process_failed"
    elif not process.running:
        process_status = "pending"

    stages: list[dict[str, Any]] = []
    for index, stage in enumerate(STAGE_ORDER):
        stage_status = "pending"
        stage_summary = ""
        if process_status == "running" and index == 0:
            stage_status = "running"
            stage_summary = "onboarding process started, waiting for run root"
        elif process_status == "process_failed" and index == 0:
            stage_status = "failed"
            stage_summary = "process finished before run root was created"
        stages.append(
            {
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "status": stage_status,
                "status_label": STATUS_LABELS.get(stage_status, "Unknown"),
                "summary": stage_summary,
                "started_at": process.started_at if index == 0 and process is not None else "",
                "finished_at": process.finished_at if index == 0 and process is not None else "",
                "artifact_count": 0,
                "artifact_types": [],
            }
        )

    return {
        "run": {
            "run_id": run_id,
            "site": site,
            "source_root": "",
            "engine": "v2",
            "status": process_status,
            "status_label": STATUS_LABELS.get(process_status, "Unknown"),
            "run_root": str(run_root.resolve()),
            "stopped_for_review": False,
            "repair_attempt_count": 0,
            "latest_failure_signature": "",
            "latest_rewind_to": "",
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
        "repair": {
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
        },
        "recent_events": [],
        "repair_events": [],
        "details": {
            "analysis": {"cards": [], "highlights": [], "candidates": [], "confidence_notes": []},
            "planning": {"cards": [], "target_bindings": [], "validation_plan": [], "risks": []},
            "compile": {
                "cards": [],
                "host_targets": [],
                "chatbot_targets": [],
                "operation_mix": [],
                "preflight": {"passed": False, "summary": "", "scan_paths": []},
            },
            "apply": {"cards": [], "paths": [], "workspace_paths": {}, "applied_files": []},
            "export": {"cards": [], "paths": [], "failure_summary": ""},
            "validation": {
                "passed": False,
                "cards": [],
                "checks": [],
                "proofs": [],
                "covered_flows": [],
                "flow_reports": [],
                "sampled_order_id": "",
                "validated_user_id": "",
            },
        },
    }


def _service_key(site: str, service_name: str) -> str:
    return f"{site}:{service_name}"


def _service_status(*, running: bool, ready: bool, returncode: int | None) -> str:
    if returncode not in (None, 0):
        return "failed"
    if ready:
        return "ready"
    if running:
        return "starting"
    return "pending"


def _probe_tcp_port(port: int, *, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http_url(url: str, *, timeout: float = 0.7) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            return int(status) == 200
    except urllib.error.HTTPError as exc:
        return int(exc.code) == 200
    except OSError:
        return False


def _service_ready(record: ServiceProcessRecord) -> bool:
    if record.returncode is not None:
        return False
    if record.healthcheck_url:
        return _probe_http_url(record.healthcheck_url)
    if record.healthcheck_port is not None:
        return _probe_tcp_port(record.healthcheck_port)
    return True


def _service_snapshot(
    service_name: str,
    label: str,
    *,
    run_id: str,
    status: str,
    reason: str = "",
    url: str | None = None,
    log_path: str | None = None,
    working_directory: str | None = None,
    pid: int | None = None,
    command: list[str] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    returncode: int | None = None,
) -> dict[str, Any]:
    return {
        "name": service_name,
        "label": label,
        "run_id": run_id,
        "running": status in {"starting", "ready"},
        "ready": status == "ready",
        "status": status,
        "status_label": SERVICE_STATUS_LABELS.get(status, "Unknown"),
        "reason": reason,
        "url": url or "",
        "log_path": log_path or "",
        "working_directory": working_directory or "",
        "pid": pid,
        "command": list(command or []),
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": returncode,
    }


def _snapshot_from_service_record(record: ServiceProcessRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    synced = _sync_service_record(record)
    ready = _service_ready(synced)
    status = _service_status(
        running=synced.returncode is None,
        ready=ready,
        returncode=synced.returncode,
    )
    reason = ""
    if status == "starting":
        reason = "service is starting"
    elif status == "failed":
        reason = f"process exited with code {synced.returncode}"
    elif status == "ready":
        reason = "service is ready"
    return _service_snapshot(
        synced.service_name,
        synced.label,
        run_id=synced.run_id,
        status=status,
        reason=reason,
        url=synced.url,
        log_path=str(synced.log_path.resolve()),
        working_directory=synced.working_directory,
        pid=synced.process.pid,
        command=synced.command,
        started_at=synced.started_at,
        finished_at=synced.finished_at,
        returncode=synced.returncode,
    )


def _terminate_service(record: ServiceProcessRecord) -> None:
    synced = _sync_service_record(record)
    if synced.returncode is None:
        synced.process.terminate()
        try:
            synced.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            synced.process.kill()
            synced.process.wait(timeout=5)
        synced.returncode = synced.process.returncode
        synced.finished_at = _utcnow()
    _close_log_handle(synced.log_handle)


def _launch_service(*, site: str, run_id: str, spec: ServiceLaunchSpec) -> ServiceProcessRecord:
    service_log_dir = ROOT / "onmo" / "logs" / "services"
    service_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = service_log_dir / f"{site}-{spec.service_name}.log"
    log_handle = log_path.open("w", encoding="utf-8")

    env = _build_child_env(extra=spec.env_overrides)
    process = subprocess.Popen(
        spec.command,
        cwd=str(spec.working_directory),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        creationflags=_subprocess_creationflags(),
    )
    return ServiceProcessRecord(
        site=site,
        run_id=run_id,
        service_name=spec.service_name,
        label=spec.label,
        working_directory=str(spec.working_directory),
        command=list(spec.command),
        process=process,
        log_path=log_path,
        log_handle=log_handle,
        started_at=_utcnow(),
        url=spec.url,
        healthcheck_url=spec.healthcheck_url,
        healthcheck_port=spec.healthcheck_port,
        env_overrides=dict(spec.env_overrides),
    )


def _ensure_service_process(*, site: str, run_id: str, spec: ServiceLaunchSpec) -> dict[str, Any]:
    key = _service_key(site, spec.service_name)
    with _REGISTRY_LOCK:
        existing = _SERVICE_REGISTRY.get(key)
        if existing is not None:
            synced = _sync_service_record(existing)
            if (
                synced.returncode is None
                and synced.run_id == run_id
                and synced.working_directory == str(spec.working_directory)
                and synced.command == spec.command
            ):
                return _snapshot_from_service_record(synced) or _service_snapshot(
                    spec.service_name,
                    spec.label,
                    run_id=run_id,
                    status="starting",
                    url=spec.url,
                )
            _terminate_service(synced)
        record = _launch_service(site=site, run_id=run_id, spec=spec)
        _SERVICE_REGISTRY[key] = record
        return _snapshot_from_service_record(record) or _service_snapshot(
            spec.service_name,
            spec.label,
            run_id=run_id,
            status="starting",
            url=spec.url,
        )


def _build_demo_service_specs(
    *,
    site: str,
    run_id: str,
    source_root: Path,
    preview_url: str,
) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    specs: list[ServiceLaunchSpec] = []
    blocked: list[dict[str, Any]] = []

    chatbot_root = (ROOT / "chatbot").resolve()
    if not (chatbot_root / "server_fastapi.py").exists():
        blocked.append(
            _service_snapshot(
                "chatbot",
                "Chatbot server",
                run_id=run_id,
                status="blocked",
                reason="chatbot/server_fastapi.py not found",
                url="http://127.0.0.1:8100",
            )
        )
    else:
        chatbot_env = {
            "PYTHONPATH": str(ROOT),
            "BILYEO_API_URL": "http://127.0.0.1:5000",
        }
        specs.append(
            ServiceLaunchSpec(
                service_name="chatbot",
                label="Chatbot server",
                working_directory=ROOT,
                command=[
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "chatbot.server_fastapi:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8100",
                ],
                url="http://127.0.0.1:8100",
                healthcheck_url="http://127.0.0.1:8100/widget.js",
                env_overrides=chatbot_env,
            )
        )

    backend_root = (source_root / "backend").resolve() if (source_root / "backend").exists() else source_root.resolve()
    backend_entrypoint = backend_root / "app.py"
    if not backend_entrypoint.exists():
        blocked.append(
            _service_snapshot(
                "backend",
                "Bilyeo backend",
                run_id=run_id,
                status="blocked",
                reason="bilyeo backend/app.py not found",
                url="http://127.0.0.1:5000",
            )
        )
    else:
        specs.append(
            ServiceLaunchSpec(
                service_name="backend",
                label="Bilyeo backend",
                working_directory=backend_root,
                command=[sys.executable, "app.py"],
                url="http://127.0.0.1:5000",
                healthcheck_port=5000,
            )
        )

    frontend_root = (source_root / "frontend").resolve()
    package_json = frontend_root / "package.json"
    if not package_json.exists():
        blocked.append(
            _service_snapshot(
                "frontend",
                "Bilyeo frontend",
                run_id=run_id,
                status="blocked",
                reason="bilyeo frontend/package.json not found",
                url=preview_url,
            )
        )
    else:
        specs.append(
            ServiceLaunchSpec(
                service_name="frontend",
                label="Bilyeo frontend",
                working_directory=frontend_root,
                command=["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "3000"],
                url=preview_url,
                healthcheck_port=3000,
                env_overrides={"VITE_CHATBOT_SERVER_BASE_URL": "http://127.0.0.1:8100"},
            )
        )

    return specs, blocked


def _resolve_source_root_for_run(*, site: str, run_id: str, run_payload: dict[str, Any]) -> Path:
    record = _lookup_record(site, run_id)
    if record is not None:
        return Path(record.source_root).resolve()
    source_root = str((run_payload.get("run") or {}).get("source_root") or "").strip()
    return _resolve_repo_path(source_root)


def _collect_service_snapshots(*, site: str, run_id: str) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    with _REGISTRY_LOCK:
        for service_name in DEMO_SERVICE_NAMES:
            record = _SERVICE_REGISTRY.get(_service_key(site, service_name))
            if record is None or record.run_id != run_id:
                continue
            snapshot = _snapshot_from_service_record(record)
            if snapshot is not None:
                snapshots.append(snapshot)
    return snapshots


def _build_demo_payload(*, run_payload: dict[str, Any], service_snapshots: list[dict[str, Any]], preview_url: str) -> dict[str, Any]:
    ordered_services = sorted(
        service_snapshots,
        key=lambda item: DEMO_SERVICE_NAMES.index(str(item.get("name") or "frontend"))
        if str(item.get("name") or "") in DEMO_SERVICE_NAMES
        else 99,
    )
    ready_count = sum(1 for item in ordered_services if item.get("ready"))
    total_count = len(ordered_services)
    blocked_services = [
        item for item in ordered_services if str(item.get("status") or "") in {"blocked", "failed"}
    ]
    validation_passed = bool(((run_payload.get("details") or {}).get("validation") or {}).get("passed"))

    if validation_passed and blocked_services:
        status = "failed"
        status_label = "Bilyeo blocked"
        message = str(blocked_services[0].get("reason") or "one or more bilyeo services could not start")
    elif validation_passed and total_count == 3 and ready_count == total_count:
        status = "ready"
        status_label = "Bilyeo Ready"
        message = "chatbot, bilyeo backend, frontend are all live"
    elif validation_passed and any(item.get("running") for item in ordered_services):
        status = "starting"
        status_label = "Launching bilyeo"
        message = "validated run finished, starting bilyeo live services"
    elif validation_passed:
        status = "pending"
        status_label = "Validated"
        message = "validated run is ready to launch bilyeo services"
    elif (run_payload.get("run") or {}).get("status") in {"failed", "failed_human_review", "process_failed"}:
        status = "failed"
        status_label = "Bilyeo blocked"
        message = "run must pass validation before bilyeo can start"
    else:
        status = "pending"
        status_label = "Waiting for validation"
        message = "bilyeo services launch after validation passes"

    return {
        "status": status,
        "status_label": status_label,
        "message": message,
        "ready": status == "ready",
        "preview_url": preview_url,
        "services": ordered_services,
    }


def _ensure_demo_services(*, site: str, run_id: str, run_payload: dict[str, Any], preview_url: str) -> list[dict[str, Any]]:
    details = run_payload.get("details") or {}
    validation_details = details.get("validation") or {}

    if not bool(validation_details.get("passed")):
        return _collect_service_snapshots(site=site, run_id=run_id)

    source_root = _resolve_source_root_for_run(site=site, run_id=run_id, run_payload=run_payload)
    if not source_root.exists():
        return [
            _service_snapshot(
                "backend",
                "Bilyeo backend",
                run_id=run_id,
                status="blocked",
                reason=f"source root not found: {source_root}",
                url="http://127.0.0.1:5000",
            ),
            _service_snapshot(
                "chatbot",
                "Chatbot server",
                run_id=run_id,
                status="blocked",
                reason=f"source root not found: {source_root}",
                url="http://127.0.0.1:8100",
            ),
            _service_snapshot(
                "frontend",
                "Bilyeo frontend",
                run_id=run_id,
                status="blocked",
                reason=f"source root not found: {source_root}",
                url=preview_url,
            ),
        ]
    specs, blocked = _build_demo_service_specs(
        site=site,
        run_id=run_id,
        source_root=source_root,
        preview_url=preview_url,
    )

    live: list[dict[str, Any]] = []
    for spec in specs:
        live.append(_ensure_service_process(site=site, run_id=run_id, spec=spec))
    return blocked + live


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "generated_root_default": str(DEFAULT_GENERATED_ROOT),
        "runtime_root_default": str(DEFAULT_RUNTIME_ROOT),
        "project_root": str(ROOT),
    }


@app.get("/api/config")
def config() -> dict[str, object]:
    return {
        "generated_root_default": DEFAULT_GENERATED_ROOT_ARG,
        "runtime_root_default": DEFAULT_RUNTIME_ROOT_ARG,
        "preview_url_default": DEFAULT_PREVIEW_URL,
        "project_options": _project_options(),
        "llm_provider_default": "openai",
        "llm_model_default": "gpt-5.2",
    }


@app.get("/api/onboarding/runs")
def list_runs(
    generated_root: str = Query(default=str(DEFAULT_GENERATED_ROOT)),
    site: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, object]:
    generated_path = _resolve_repo_path(generated_root, default=DEFAULT_GENERATED_ROOT)
    return {"items": discover_runs(generated_root=generated_path, site=site, limit=limit)}


@app.post("/api/onboarding/start")
def start_onboarding(request: StartRunRequest) -> dict[str, object]:
    site = request.site.strip()
    run_id = (request.run_id or f"{site}-demo-{_timestamp_slug()}").strip()
    source_root_arg = request.source_root.strip()
    generated_root_arg = (request.generated_root or "").strip() or DEFAULT_GENERATED_ROOT_ARG
    runtime_root_arg = (request.runtime_root or "").strip() or DEFAULT_RUNTIME_ROOT_ARG

    source_root = _resolve_repo_path(source_root_arg)
    generated_root = _resolve_repo_path(generated_root_arg, default=DEFAULT_GENERATED_ROOT)
    runtime_root = _resolve_repo_path(runtime_root_arg, default=DEFAULT_RUNTIME_ROOT)

    if not source_root.exists():
        raise HTTPException(status_code=404, detail=f"Source root not found: {source_root}")

    generated_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    _clear_previous_run_state(
        site=site,
        run_id=run_id,
        generated_root=generated_root,
        runtime_root=runtime_root,
    )
    _clear_site_services(site)
    log_dir = ROOT / "onmo" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{site}-{run_id}.log"
    log_handle = log_path.open("w", encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "chatbot.scripts.run_onboarding_generation",
        "--site",
        site,
        "--source-root",
        source_root_arg,
        "--generated-root",
        generated_root_arg,
        "--runtime-root",
        runtime_root_arg,
        "--run-id",
        run_id,
    ]
    if request.llm_provider and request.llm_provider.strip():
        command.extend(["--llm-provider", request.llm_provider.strip()])
    if request.llm_model and request.llm_model.strip():
        command.extend(["--llm-model", request.llm_model.strip()])
    if request.chatbot_server_base_url and request.chatbot_server_base_url.strip():
        command.extend(["--chatbot-server-base-url", request.chatbot_server_base_url.strip()])
    if request.smoke_username:
        command.extend(["--smoke-username", request.smoke_username])
    if request.smoke_email:
        command.extend(["--smoke-email", request.smoke_email])
    if request.smoke_password:
        command.extend(["--smoke-password", request.smoke_password])

    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=_build_child_env(),
        creationflags=_subprocess_creationflags(),
    )
    record = RunProcessRecord(
        site=site,
        run_id=run_id,
        generated_root=str(generated_root),
        runtime_root=str(runtime_root),
        source_root=str(source_root),
        preview_url=(request.preview_url or "").strip() or None,
        command=command,
        process=process,
        log_path=log_path,
        log_handle=log_handle,
        started_at=_utcnow(),
    )
    with _REGISTRY_LOCK:
        _RUN_REGISTRY[f"{site}:{run_id}"] = record

    return {
        "run_id": run_id,
        "site": site,
        "run_root": str((generated_root / site / run_id).resolve()),
        "log_path": str(log_path.resolve()),
        "generated_root": str(generated_root.resolve()),
        "runtime_root": str(runtime_root.resolve()),
        "command": command,
        "status": "running",
    }


@app.get("/api/onboarding/runs/{run_id}")
def get_run_dashboard(
    run_id: str,
    site: str = Query(..., min_length=1),
    generated_root: str = Query(default=str(DEFAULT_GENERATED_ROOT)),
) -> dict[str, object]:
    generated_path = _resolve_repo_path(generated_root, default=DEFAULT_GENERATED_ROOT)
    run_root = generated_path / site / run_id
    process = _snapshot_from_record(_lookup_record(site, run_id))
    if not run_root.exists():
        if process is None:
            raise HTTPException(status_code=404, detail=f"Run root not found: {run_root}")
        payload = _build_pending_run_dashboard(
            site=site,
            run_id=run_id,
            run_root=run_root,
            process=process,
        )
    else:
        payload = load_run_dashboard(run_root=run_root, process=process)
    preview_url = (
        (process.preview_url if process is not None else None)
        or str((payload.get("process") or {}).get("preview_url") or "").strip()
        or DEFAULT_PREVIEW_URL
    )
    services = _ensure_demo_services(site=site, run_id=run_id, run_payload=payload, preview_url=preview_url)
    payload["services"] = services
    payload["demo"] = _build_demo_payload(run_payload=payload, service_snapshots=services, preview_url=preview_url)
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("onmo.app:app", host="127.0.0.1", port=8899, reload=_onmo_reload_enabled())
