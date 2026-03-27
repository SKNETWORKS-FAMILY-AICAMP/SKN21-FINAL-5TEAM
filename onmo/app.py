from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock, Thread
from typing import Any, TextIO

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from onmo.dashboard import (
    ProcessSnapshot,
    STAGE_LABELS,
    STAGE_ORDER,
    STATUS_LABELS,
    discover_runs,
    inject_import_stage,
    load_run_dashboard,
)
from onmo.github_imports import (
    GitHubImportError,
    GitHubRepoProbe,
    build_github_authorize_url,
    download_github_archive,
    exchange_github_code_for_token,
    normalize_site_slug,
    probe_github_repository,
    resolve_github_source_root,
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
GITHUB_IMPORT_ROOT_NAME = "_github_imports"
GITHUB_IMPORT_TTL = timedelta(hours=12)
GITHUB_OAUTH_STATE_TTL = timedelta(minutes=15)
GITHUB_MODE_MESSAGE = "GitHub 가져오기 런은 라이브 프리뷰를 실행하지 않습니다."


@dataclass(slots=True)
class GitHubImportRun:
    run_id: str
    site: str
    repo_url: str
    owner: str
    repo: str
    default_branch: str
    generated_root: str
    runtime_root: str
    created_at: str
    updated_at: str
    status: str
    summary: str = ""
    error_message: str = ""
    source_subdir: str = ""
    source_root: str = ""
    workdir_root: str = ""
    finished_at: str | None = None
    demo_enabled: bool = False


@dataclass(slots=True)
class GitHubOAuthState:
    state: str
    run_id: str
    expires_at: str


class GitHubImportRequest(BaseModel):
    repo_url: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="ignore")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _parse_iso8601(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _github_import_root(runtime_root: str | Path) -> Path:
    return Path(runtime_root) / GITHUB_IMPORT_ROOT_NAME


def _github_workdir_root(*, runtime_root: str | Path, site: str, run_id: str) -> Path:
    return _github_import_root(runtime_root) / site / run_id


def _github_public_base_url(request: Request | None = None) -> str:
    configured = str(os.getenv("ONMO_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    if request is not None:
        return str(request.base_url).rstrip("/")
    return "http://127.0.0.1:8899"


def _github_callback_url(request: Request | None = None) -> str:
    return f"{_github_public_base_url(request)}/auth/github/callback"


def _cleanup_expired_github_imports() -> None:
    now = datetime.now(UTC)
    expired_runs: list[str] = []
    expired_states: list[str] = []
    with _REGISTRY_LOCK:
        for run_id, record in _GITHUB_IMPORT_REGISTRY.items():
            terminal = record.status in {"completed", "failed"}
            anchor = _parse_iso8601(record.finished_at if terminal else record.updated_at)
            if not terminal or anchor is None:
                continue
            if now - anchor >= GITHUB_IMPORT_TTL:
                expired_runs.append(run_id)
        for state_key, state_record in _GITHUB_OAUTH_STATE_REGISTRY.items():
            expires_at = _parse_iso8601(state_record.expires_at)
            if expires_at is not None and now >= expires_at:
                expired_states.append(state_key)

        stale_records = [(_GITHUB_IMPORT_REGISTRY.pop(run_id, None)) for run_id in expired_runs]
        for state_key in expired_states:
            _GITHUB_OAUTH_STATE_REGISTRY.pop(state_key, None)

    for record in stale_records:
        if record is None:
            continue
        workdir = Path(str(record.workdir_root or "").strip())
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)


def _lookup_github_import_run(run_id: str) -> GitHubImportRun | None:
    with _REGISTRY_LOCK:
        return _GITHUB_IMPORT_REGISTRY.get(run_id)


def _store_github_import_run(record: GitHubImportRun) -> GitHubImportRun:
    with _REGISTRY_LOCK:
        _GITHUB_IMPORT_REGISTRY[record.run_id] = record
    return record


def _update_github_import_run(run_id: str, **updates: Any) -> GitHubImportRun | None:
    with _REGISTRY_LOCK:
        record = _GITHUB_IMPORT_REGISTRY.get(run_id)
        if record is None:
            return None
        for key, value in updates.items():
            setattr(record, key, value)
        record.updated_at = _utcnow()
        return record


def _new_github_import_run(*, repo_probe: GitHubRepoProbe) -> GitHubImportRun:
    site_hint = repo_probe.source_subdir.rsplit("/", 1)[-1] if repo_probe.source_subdir else repo_probe.repo
    site = normalize_site_slug(site_hint)
    timestamp = _timestamp_slug()
    run_id = f"{site}-github-{timestamp}"
    return GitHubImportRun(
        run_id=run_id,
        site=site,
        repo_url=repo_probe.repo_url,
        owner=repo_probe.owner,
        repo=repo_probe.repo,
        default_branch=repo_probe.default_branch,
        generated_root=DEFAULT_GENERATED_ROOT_ARG,
        runtime_root=DEFAULT_RUNTIME_ROOT_ARG,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        status="pending_auth" if repo_probe.requires_auth else "importing",
        summary=(
            "GitHub 인증이 필요합니다."
            if repo_probe.requires_auth
            else "GitHub 저장소 소스를 내려받는 중입니다."
        ),
        source_subdir=repo_probe.source_subdir,
        demo_enabled=False,
    )


def _github_import_stage_status(record: GitHubImportRun) -> str:
    if record.status == "failed":
        return "failed"
    if record.status == "completed":
        return "completed"
    return "running"


def _github_import_summary(record: GitHubImportRun) -> str:
    if str(record.summary or "").strip():
        return record.summary
    if record.status == "pending_auth":
        return "GitHub 인증 승인을 기다리는 중입니다."
    if record.status == "failed":
        return record.error_message or "GitHub 가져오기에 실패했습니다."
    if record.status == "completed":
        return "GitHub 소스를 가져온 뒤 온보딩을 시작했습니다."
    return "GitHub 저장소 소스를 내려받는 중입니다."


def _github_oauth_configured() -> bool:
    return bool(str(os.getenv("GITHUB_CLIENT_ID") or "").strip()) and bool(
        str(os.getenv("GITHUB_CLIENT_SECRET") or "").strip()
    )


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
    demo_enabled: bool
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
_GITHUB_IMPORT_REGISTRY: dict[str, GitHubImportRun] = {}
_GITHUB_OAUTH_STATE_REGISTRY: dict[str, GitHubOAuthState] = {}


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


def _probe_github_repository(repo_url: str, access_token: str | None = None) -> GitHubRepoProbe:
    return probe_github_repository(repo_url, access_token=access_token)


def _start_github_import_background(intent: GitHubImportRun, access_token: str | None = None) -> None:
    worker = Thread(
        target=_run_github_import_job,
        kwargs={"run_id": intent.run_id, "access_token": access_token},
        daemon=True,
        name=f"onmo-github-import-{intent.run_id}",
    )
    worker.start()


def _oauth_state_redirect_target(request: Request, run_id: str) -> str:
    import_run = _lookup_github_import_run(run_id)
    site = import_run.site if import_run is not None else ""
    generated_root = import_run.generated_root if import_run is not None else DEFAULT_GENERATED_ROOT_ARG
    base_url = _github_public_base_url(request)
    return f"{base_url}/?{urllib.parse.urlencode({'site': site, 'run_id': run_id, 'generated_root': generated_root})}"


def _launch_onboarding_process(
    *,
    site: str,
    source_root_arg: str,
    generated_root_arg: str,
    runtime_root_arg: str,
    run_id: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    chatbot_server_base_url: str | None = None,
    preview_url: str | None = None,
    smoke_username: str | None = None,
    smoke_email: str | None = None,
    smoke_password: str | None = None,
    demo_enabled: bool = True,
) -> dict[str, object]:
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
    if llm_provider and llm_provider.strip():
        command.extend(["--llm-provider", llm_provider.strip()])
    if llm_model and llm_model.strip():
        command.extend(["--llm-model", llm_model.strip()])
    if chatbot_server_base_url and chatbot_server_base_url.strip():
        command.extend(["--chatbot-server-base-url", chatbot_server_base_url.strip()])
    if smoke_username:
        command.extend(["--smoke-username", smoke_username])
    if smoke_email:
        command.extend(["--smoke-email", smoke_email])
    if smoke_password:
        command.extend(["--smoke-password", smoke_password])

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
        preview_url=(preview_url or "").strip() or None,
        demo_enabled=demo_enabled,
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


def _run_github_import_job(*, run_id: str, access_token: str | None = None) -> None:
    record = _lookup_github_import_run(run_id)
    if record is None:
        return

    try:
        _update_github_import_run(run_id, status="importing", summary="GitHub 저장소 정보를 확인하는 중입니다.")
        probe = _probe_github_repository(record.repo_url, access_token=access_token)
        workdir_root = _github_workdir_root(
            runtime_root=record.runtime_root,
            site=record.site,
            run_id=record.run_id,
        )
        if workdir_root.exists():
            shutil.rmtree(workdir_root, ignore_errors=True)
        archive_root = workdir_root / "archive"
        extracted_root = download_github_archive(
            owner=probe.owner,
            repo=probe.repo,
            branch=probe.default_branch,
            destination_root=archive_root,
            access_token=access_token,
        )
        selected_source_root = resolve_github_source_root(extracted_root, probe.source_subdir or record.source_subdir)
        source_root = workdir_root / "source"
        source_root.parent.mkdir(parents=True, exist_ok=True)
        if source_root.exists():
            shutil.rmtree(source_root, ignore_errors=True)
        shutil.move(str(selected_source_root), str(source_root))
        _update_github_import_run(
            run_id,
            owner=probe.owner,
            repo=probe.repo,
            default_branch=probe.default_branch,
            source_subdir=probe.source_subdir,
            source_root=str(source_root.resolve()),
            workdir_root=str(workdir_root.resolve()),
            summary="GitHub 소스를 가져왔습니다. 온보딩을 시작합니다.",
        )
        _launch_onboarding_process(
            site=record.site,
            source_root_arg=str(source_root.resolve()),
            generated_root_arg=record.generated_root,
            runtime_root_arg=record.runtime_root,
            run_id=record.run_id,
            preview_url=None,
            demo_enabled=False,
        )
        _update_github_import_run(
            run_id,
            status="completed",
            summary="GitHub 소스를 가져온 뒤 온보딩을 시작했습니다.",
            finished_at=_utcnow(),
        )
    except HTTPException as exc:
        _update_github_import_run(
            run_id,
            status="failed",
            error_message=str(exc.detail),
            summary=str(exc.detail),
            finished_at=_utcnow(),
        )
    except GitHubImportError as exc:
        _update_github_import_run(
            run_id,
            status="failed",
            error_message=str(exc),
            summary=str(exc),
            finished_at=_utcnow(),
        )
    except Exception:
        _update_github_import_run(
            run_id,
            status="failed",
            error_message="GitHub 가져오기 중 알 수 없는 오류가 발생했습니다.",
            summary="GitHub 가져오기 중 알 수 없는 오류가 발생했습니다.",
            finished_at=_utcnow(),
        )


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


def _build_disabled_demo_payload() -> dict[str, Any]:
    return {
        "status": "disabled",
        "status_label": "GitHub Mode",
        "message": GITHUB_MODE_MESSAGE,
        "ready": False,
        "preview_url": None,
        "services": [],
    }


def _github_mode_enabled_for_run(
    *,
    site: str,
    run_id: str,
    process_record: RunProcessRecord | None,
) -> bool:
    import_run = _lookup_github_import_run(run_id)
    if import_run is not None:
        return not import_run.demo_enabled
    if process_record is not None:
        return not process_record.demo_enabled
    return False


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


def _decorate_dashboard_with_github_import(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    import_run = _lookup_github_import_run(run_id)
    if import_run is None:
        return payload

    stage_status = _github_import_stage_status(import_run)
    summary = _github_import_summary(import_run)
    updated = inject_import_stage(
        payload,
        status=stage_status,
        summary=summary,
        started_at=import_run.created_at,
        finished_at=str(import_run.finished_at or ""),
    )
    details = dict(updated.get("details") or {})
    import_details = dict(details.get("import") or {})
    import_details["cards"] = [
        {"label": "Repo", "value": f"{import_run.owner}/{import_run.repo}"},
        {"label": "Branch", "value": import_run.default_branch or "-"},
        {"label": "Path", "value": import_run.source_subdir or "/"},
        {"label": "Status", "value": import_details.get("status_label") or STATUS_LABELS.get(stage_status, "Unknown")},
        {"label": "Source", "value": import_run.source_root or "-"},
    ]
    import_details["summary"] = summary
    details["import"] = import_details
    updated["details"] = details
    run_payload = dict(updated.get("run") or {})
    if not str(run_payload.get("source_root") or "").strip() and str(import_run.source_root or "").strip():
        run_payload["source_root"] = import_run.source_root
    if stage_status == "failed":
        run_payload["status"] = "failed"
        run_payload["status_label"] = STATUS_LABELS.get("failed", "Failed")
    elif run_payload.get("status") in {"pending", "unknown"}:
        run_payload["status"] = "running"
        run_payload["status_label"] = STATUS_LABELS.get("running", "Running")
    updated["run"] = run_payload
    return updated


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
        "github_import_enabled": True,
        "github_oauth_configured": _github_oauth_configured(),
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
    return _launch_onboarding_process(
        site=site,
        source_root_arg=request.source_root.strip(),
        generated_root_arg=(request.generated_root or "").strip() or DEFAULT_GENERATED_ROOT_ARG,
        runtime_root_arg=(request.runtime_root or "").strip() or DEFAULT_RUNTIME_ROOT_ARG,
        run_id=run_id,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        chatbot_server_base_url=request.chatbot_server_base_url,
        preview_url=(request.preview_url or "").strip() or None,
        smoke_username=request.smoke_username,
        smoke_email=request.smoke_email,
        smoke_password=request.smoke_password,
        demo_enabled=True,
    )


@app.post("/api/onboarding/github/imports")
def create_github_import(request: GitHubImportRequest, http_request: Request) -> dict[str, object]:
    _cleanup_expired_github_imports()
    try:
        repo_probe = _probe_github_repository(request.repo_url.strip())
    except GitHubImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import_run = _store_github_import_run(_new_github_import_run(repo_probe=repo_probe))
    if repo_probe.requires_auth:
        return {
            "status": "auth_required",
            "run_id": import_run.run_id,
            "site": import_run.site,
            "authorize_url": (
                f"{_github_public_base_url(http_request)}/auth/github/start?"
                f"{urllib.parse.urlencode({'run_id': import_run.run_id})}"
            ),
        }
    _start_github_import_background(import_run)
    return {
        "status": "importing",
        "run_id": import_run.run_id,
        "site": import_run.site,
    }


@app.get("/auth/github/start")
def start_github_oauth(request: Request, run_id: str = Query(..., min_length=1)) -> RedirectResponse:
    _cleanup_expired_github_imports()
    import_run = _lookup_github_import_run(run_id)
    if import_run is None:
        raise HTTPException(status_code=404, detail="GitHub import run not found")
    if not str(os.getenv("GITHUB_CLIENT_ID") or "").strip():
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")

    state = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + GITHUB_OAUTH_STATE_TTL
    with _REGISTRY_LOCK:
        _GITHUB_OAUTH_STATE_REGISTRY[state] = GitHubOAuthState(
            state=state,
            run_id=run_id,
            expires_at=expires_at.isoformat(),
        )
    authorize_url = build_github_authorize_url(
        client_id=str(os.getenv("GITHUB_CLIENT_ID") or "").strip(),
        redirect_uri=_github_callback_url(request),
        state=state,
    )
    _update_github_import_run(run_id, status="pending_auth", summary="GitHub 인증 승인을 기다리는 중입니다.")
    return RedirectResponse(authorize_url)


@app.get("/auth/github/callback")
def github_oauth_callback(
    request: Request,
    state: str = Query(..., min_length=1),
    code: str = Query(..., min_length=1),
) -> RedirectResponse:
    _cleanup_expired_github_imports()
    with _REGISTRY_LOCK:
        oauth_state = _GITHUB_OAUTH_STATE_REGISTRY.pop(state, None)
    if oauth_state is None:
        raise HTTPException(status_code=400, detail="Invalid or expired GitHub OAuth state")

    import_run = _lookup_github_import_run(oauth_state.run_id)
    if import_run is None:
        raise HTTPException(status_code=404, detail="GitHub import run not found")
    if not _github_oauth_configured():
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")

    try:
        token = exchange_github_code_for_token(
            code=code,
            client_id=str(os.getenv("GITHUB_CLIENT_ID") or "").strip(),
            client_secret=str(os.getenv("GITHUB_CLIENT_SECRET") or "").strip(),
            redirect_uri=_github_callback_url(request),
        )
    except GitHubImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _update_github_import_run(
        import_run.run_id,
        status="importing",
        summary="GitHub 인증이 완료되었습니다. 저장소를 가져오는 중입니다.",
    )
    _start_github_import_background(import_run, access_token=token)
    return RedirectResponse(_oauth_state_redirect_target(request, import_run.run_id))


@app.get("/api/onboarding/runs/{run_id}")
def get_run_dashboard(
    run_id: str,
    site: str = Query(..., min_length=1),
    generated_root: str = Query(default=str(DEFAULT_GENERATED_ROOT)),
) -> dict[str, object]:
    _cleanup_expired_github_imports()
    generated_path = _resolve_repo_path(generated_root, default=DEFAULT_GENERATED_ROOT)
    run_root = generated_path / site / run_id
    process_record = _lookup_record(site, run_id)
    process = _snapshot_from_record(process_record)
    if not run_root.exists():
        if process is None and _lookup_github_import_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Run root not found: {run_root}")
        payload = _build_pending_run_dashboard(
            site=site,
            run_id=run_id,
            run_root=run_root,
            process=process,
        )
    else:
        payload = load_run_dashboard(run_root=run_root, process=process)
    payload = _decorate_dashboard_with_github_import(payload, run_id)
    github_mode = _github_mode_enabled_for_run(site=site, run_id=run_id, process_record=process_record)
    if github_mode:
        payload["services"] = []
        payload["demo"] = _build_disabled_demo_payload()
        return payload

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
