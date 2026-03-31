from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock, Thread
from typing import Any, TextIO

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from onmo.dashboard import (
    ProcessSnapshot,
    STAGE_LABELS,
    STAGE_ORDER,
    STATUS_LABELS,
    decorate_dashboard_payload,
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
GITHUB_IMPORT_ENV_TARGET_PATHS = {".env", "backend/.env"}
STATIC_ASSET_VERSION_TOKEN = "__ONMO_ASSET_VERSION__"


@dataclass(frozen=True, slots=True)
class BootstrapLaunchProfile:
    compose_service: str
    wait_strategy: str | None = None
    wait_target: str | None = None
    timeout_seconds: int = 120


@dataclass(frozen=True, slots=True)
class LaunchServiceProfile:
    relative_root: str
    required_path: str
    command: tuple[str, ...]
    env_overrides: dict[str, str] = field(default_factory=dict)
    healthcheck_port: int | None = None
    healthcheck_url: str | None = None
    prepare_command: tuple[str, ...] | None = None
    prepare_sentinel: str | None = None


@dataclass(frozen=True, slots=True)
class KnownLaunchProfile:
    site: str
    label: str
    preview_url: str
    backend_url: str
    frontend_url: str
    frontend_api_base_template: str = "{backend_url}"
    chatbot_url: str = "http://127.0.0.1:8100"
    preview_workspace_preference: str = "export_replay_then_apply_then_source"
    bootstrap: BootstrapLaunchProfile | None = None
    backend: LaunchServiceProfile | None = None
    frontend: LaunchServiceProfile | None = None
    chatbot: LaunchServiceProfile | None = None


KNOWN_LAUNCH_PROFILES: dict[str, KnownLaunchProfile] = {
    "bilyeo": KnownLaunchProfile(
        site="bilyeo",
        label="Bilyeo",
        preview_url="http://127.0.0.1:3000/bilyeo/",
        backend_url="http://127.0.0.1:5000",
        frontend_url="http://127.0.0.1:3000/bilyeo/",
        frontend_api_base_template="/api",
        bootstrap=BootstrapLaunchProfile(
            compose_service="bilyeo-oracle",
            wait_strategy="tcp_port",
            wait_target="127.0.0.1:1521",
            timeout_seconds=60,
        ),
        backend=LaunchServiceProfile(
            relative_root="backend",
            required_path="app.py",
            command=("{python}", "app.py"),
            healthcheck_port=5000,
        ),
        frontend=LaunchServiceProfile(
            relative_root="frontend",
            required_path="package.json",
            command=("npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "3000"),
            healthcheck_port=3000,
            env_overrides={
                "VITE_API_BASE": "{frontend_api_base}",
                "VITE_CHATBOT_SERVER_BASE_URL": "{chatbot_url}",
                "VITE_CAPABILITY_PROFILE": "{capability_profile}",
                "VITE_ENABLED_RETRIEVAL_CORPORA": "{enabled_retrieval_corpora_csv}",
            },
            prepare_command=("npm", "install"),
            prepare_sentinel="node_modules",
        ),
        chatbot=LaunchServiceProfile(
            relative_root=".",
            required_path="server_fastapi.py",
            command=("{python}", "-m", "uvicorn", "server_fastapi:app", "--host", "127.0.0.1", "--port", "8100"),
            healthcheck_url="{chatbot_url}/widget.js",
            env_overrides={
                "PYTHONPATH": "{chatbot_root}",
                "BACKEND_API_URL": "{backend_url}",
                "BILYEO_API_URL": "{backend_url}",
            },
        ),
    ),
    "food": KnownLaunchProfile(
        site="food",
        label="Food",
        preview_url="http://127.0.0.1:3000/",
        backend_url="http://127.0.0.1:8000",
        frontend_url="http://127.0.0.1:3000/",
        frontend_api_base_template="{backend_url}",
        backend=LaunchServiceProfile(
            relative_root="backend",
            required_path="manage.py",
            command=("{python}", "manage.py", "runserver", "127.0.0.1:8000"),
            healthcheck_port=8000,
            env_overrides={"DJANGO_SETTINGS_MODULE": "foodshop.settings"},
        ),
        frontend=LaunchServiceProfile(
            relative_root="frontend",
            required_path="package.json",
            command=("npm", "run", "dev"),
            healthcheck_port=3000,
            env_overrides={
                "PORT": "3000",
                "BROWSER": "none",
                "DANGEROUSLY_DISABLE_HOST_CHECK": "true",
                "REACT_APP_API_URL": "{frontend_api_base}",
                "REACT_APP_CHATBOT_SERVER_BASE_URL": "{chatbot_url}",
            },
            prepare_command=("npm", "install"),
            prepare_sentinel="node_modules",
        ),
        chatbot=LaunchServiceProfile(
            relative_root=".",
            required_path="server_fastapi.py",
            command=("{python}", "-m", "uvicorn", "server_fastapi:app", "--host", "127.0.0.1", "--port", "8100"),
            healthcheck_url="{chatbot_url}/widget.js",
            env_overrides={
                "PYTHONPATH": "{chatbot_root}",
                "BACKEND_API_URL": "{backend_url}",
            },
        ),
    ),
    "ecommerce": KnownLaunchProfile(
        site="ecommerce",
        label="Ecommerce",
        preview_url="http://127.0.0.1:3000/",
        backend_url="http://127.0.0.1:8000",
        frontend_url="http://127.0.0.1:3000/",
        frontend_api_base_template="{backend_url}",
        bootstrap=BootstrapLaunchProfile(
            compose_service="mysql",
            wait_strategy="tcp_port",
            wait_target="127.0.0.1:3306",
            timeout_seconds=60,
        ),
        backend=LaunchServiceProfile(
            relative_root="backend",
            required_path="app/main.py",
            command=("{python}", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"),
            healthcheck_url="{backend_url}/",
            env_overrides={
                "PYTHONPATH": "{service_root}",
                "DB_HOST": "127.0.0.1",
                "DB_PORT": "3306",
                "DB_USER": "ecom_user",
                "DB_PASSWORD": "ecopchatbot!",
                "DB_NAME": "ecommerce",
            },
        ),
        frontend=LaunchServiceProfile(
            relative_root="frontend",
            required_path="package.json",
            command=("npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"),
            healthcheck_port=3000,
            env_overrides={
                "NEXT_PUBLIC_API_URL": "{frontend_api_base}",
                "NEXT_PUBLIC_CHATBOT_API_URL": "{chatbot_url}",
            },
            prepare_command=("npm", "install"),
            prepare_sentinel="node_modules",
        ),
        chatbot=LaunchServiceProfile(
            relative_root=".",
            required_path="server_fastapi.py",
            command=("{python}", "-m", "uvicorn", "server_fastapi:app", "--host", "127.0.0.1", "--port", "8100"),
            healthcheck_url="{chatbot_url}/widget.js",
            env_overrides={
                "PYTHONPATH": "{chatbot_root}",
                "BACKEND_API_URL": "{backend_url}",
            },
        ),
    ),
}


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
    env_target_path: str = ""
    env_attachment_name: str = ""
    env_attachment_path: str = ""


@dataclass(slots=True)
class GitHubOAuthState:
    state: str
    run_id: str
    expires_at: str


class GitHubImportRequest(BaseModel):
    repo_url: str = Field(..., min_length=1)
    env_target_path: str = Field("", min_length=0)

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


def _normalize_github_env_target_path(value: str | None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.startswith("./"):
        raw = raw[2:]
    if raw not in GITHUB_IMPORT_ENV_TARGET_PATHS:
        allowed = ", ".join(sorted(GITHUB_IMPORT_ENV_TARGET_PATHS))
        raise HTTPException(status_code=400, detail=f"Unsupported env target path. Allowed values: {allowed}")
    return raw


def _github_import_attachment_root(*, runtime_root: str | Path, site: str, run_id: str) -> Path:
    return _github_import_root(runtime_root) / site / "_attachments" / run_id


def _store_github_import_env_attachment(
    *,
    record: GitHubImportRun,
    filename: str,
    content: bytes,
    target_path: str,
) -> GitHubImportRun:
    safe_name = Path(str(filename or "").strip() or ".env").name
    if not safe_name:
        safe_name = ".env"
    attachment_root = _github_import_attachment_root(
        runtime_root=record.runtime_root,
        site=record.site,
        run_id=record.run_id,
    )
    attachment_root.mkdir(parents=True, exist_ok=True)
    attachment_path = attachment_root / safe_name
    attachment_path.write_bytes(content)
    updated = _update_github_import_run(
        record.run_id,
        env_target_path=target_path,
        env_attachment_name=safe_name,
        env_attachment_path=str(attachment_path.resolve()),
    )
    return updated or record


def _inject_github_import_env_attachment(*, record: GitHubImportRun, source_root: Path) -> Path | None:
    attachment_raw = str(record.env_attachment_path or "").strip()
    target_path = str(record.env_target_path or "").strip()
    if not attachment_raw or not target_path:
        return None
    attachment_path = Path(attachment_raw)
    if not attachment_path.exists():
        raise GitHubImportError("첨부한 .env 파일을 찾을 수 없습니다.")
    destination = source_root / target_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(attachment_path, destination)
    return destination


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
    prepare_command: list[str] | None = None
    prepare_sentinel: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


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
    diagnostics: dict[str, Any] = field(default_factory=dict)
    finished_at: str | None = None
    returncode: int | None = None


@dataclass(frozen=True, slots=True)
class PreviewWorkspaceSelection:
    source_kind: str
    host_root: Path
    chatbot_root: Path


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


def _shutdown_child_processes() -> None:
    with _REGISTRY_LOCK:
        service_records = list(_SERVICE_REGISTRY.values())
        run_records = list(_RUN_REGISTRY.values())
        _SERVICE_REGISTRY.clear()
        _RUN_REGISTRY.clear()
    for record in service_records:
        try:
            _terminate_service(record)
        except Exception:
            continue
    for record in run_records:
        try:
            _terminate_run(record)
        except Exception:
            continue


@app.on_event("shutdown")
def _shutdown_onmo_children() -> None:
    _shutdown_child_processes()


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


def _run_root_from_record(record: RunProcessRecord) -> Path:
    return Path(record.generated_root) / record.site / record.run_id


def _read_run_summary(run_root: Path) -> dict[str, Any]:
    summary_path = run_root / "views" / "run-summary.json"
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _read_latest_artifact_payload(run_root: Path, *parts: str) -> dict[str, Any]:
    artifact_dir = run_root.joinpath("artifacts", *parts)
    if not artifact_dir.exists():
        return {}
    candidates = sorted(artifact_dir.glob("v*.json"))
    if not candidates:
        return {}
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if isinstance(payload, dict):
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return nested
        return payload
    return {}


def _resolve_existing_repo_path(raw_path: str | None) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = _resolve_repo_path(value)
    if not path.exists():
        return None
    return path


def _resolve_preview_workspace_selection(*, run_root: Path, run_payload: dict[str, Any]) -> PreviewWorkspaceSelection:
    replay_payload = _read_latest_artifact_payload(run_root, "06-export", "replay-result")
    replay_host = _resolve_existing_repo_path(replay_payload.get("host_replay_workspace_path"))
    replay_chatbot = _resolve_existing_repo_path(replay_payload.get("chatbot_replay_workspace_path"))
    if replay_host is not None and replay_chatbot is not None:
        return PreviewWorkspaceSelection(
            source_kind="export_replay_workspace",
            host_root=replay_host,
            chatbot_root=replay_chatbot,
        )

    apply_payload = _read_latest_artifact_payload(run_root, "04-apply", "apply-result")
    apply_host = _resolve_existing_repo_path(apply_payload.get("host_workspace_path"))
    apply_chatbot = _resolve_existing_repo_path(apply_payload.get("chatbot_workspace_path"))
    if apply_host is not None and apply_chatbot is not None:
        return PreviewWorkspaceSelection(
            source_kind="apply_workspace",
            host_root=apply_host,
            chatbot_root=apply_chatbot,
        )

    source_root = _resolve_existing_repo_path((run_payload.get("run") or {}).get("source_root"))
    if source_root is None:
        source_root = ROOT
    return PreviewWorkspaceSelection(
        source_kind="source_root",
        host_root=source_root,
        chatbot_root=(ROOT / "chatbot").resolve(),
    )


def _maybe_autostart_demo_services(record: RunProcessRecord) -> list[dict[str, Any]]:
    if not record.demo_enabled:
        return []
    synced = _lookup_record(record.site, record.run_id) or _sync_record(record)
    if synced.returncode is None or synced.returncode != 0:
        return []
    run_root = _run_root_from_record(synced)
    summary = _read_run_summary(run_root)
    if str(summary.get("status") or "").strip() != "exported":
        return []
    payload = load_run_dashboard(
        run_root=run_root,
        process=_snapshot_from_record(synced),
    )
    payload = _decorate_dashboard_with_github_import(payload, synced.run_id)
    launch_profile = _launch_profile_from_run(site=synced.site, run_id=synced.run_id, run_payload=payload)
    preview_url = (
        (synced.preview_url or "").strip()
        or str((payload.get("process") or {}).get("preview_url") or "").strip()
        or _launch_profile_preview_url(launch_profile)
    )
    return _ensure_demo_services(
        site=synced.site,
        run_id=synced.run_id,
        run_root=run_root,
        run_payload=payload,
        preview_url=preview_url,
    )


def _wait_and_autostart_demo_services(
    *,
    site: str,
    run_id: str,
    process: subprocess.Popen[str],
) -> None:
    try:
        process.wait()
    except Exception:
        return
    with _REGISTRY_LOCK:
        record = _RUN_REGISTRY.get(f"{site}:{run_id}")
    if record is None or record.process is not process:
        return
    _maybe_autostart_demo_services(record)


def _start_demo_autostart_watcher(record: RunProcessRecord) -> None:
    if not record.demo_enabled:
        return
    worker = Thread(
        target=_wait_and_autostart_demo_services,
        kwargs={
            "site": record.site,
            "run_id": record.run_id,
            "process": record.process,
        },
        daemon=True,
        name=f"onmo-demo-autostart-{record.run_id}",
    )
    worker.start()


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


def _launch_profile_for_site(site: str) -> KnownLaunchProfile | None:
    return KNOWN_LAUNCH_PROFILES.get(str(site or "").strip())


def _resolve_launch_profile(*, site: str, source_root: Path | None = None) -> KnownLaunchProfile | None:
    direct = _launch_profile_for_site(site)
    if direct is not None:
        return direct
    if source_root is None:
        return None
    return _launch_profile_for_site(source_root.name)


def _launch_profile_from_run(*, site: str, run_id: str, run_payload: dict[str, Any]) -> KnownLaunchProfile | None:
    try:
        source_root = _resolve_source_root_for_run(site=site, run_id=run_id, run_payload=run_payload)
    except Exception:
        source_root = None
    return _resolve_launch_profile(site=site, source_root=source_root)


def _launch_profile_preview_url(profile: KnownLaunchProfile | None, *, fallback: str | None = None) -> str:
    if profile is not None:
        return profile.preview_url
    if fallback is None:
        return ""
    return str(fallback or DEFAULT_PREVIEW_URL).strip()


def _render_launch_value(value: str, context: dict[str, str]) -> str:
    return str(value).format_map(context)


def _render_launch_values(values: dict[str, str], context: dict[str, str]) -> dict[str, str]:
    return {key: _render_launch_value(value, context) for key, value in values.items()}


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
    _start_demo_autostart_watcher(record)

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
        record = _lookup_github_import_run(run_id) or record
        _inject_github_import_env_attachment(record=record, source_root=source_root)
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
        launch_profile = _resolve_launch_profile(site=record.site, source_root=source_root)
        preview_url = _launch_profile_preview_url(launch_profile, fallback=None)
        _update_github_import_run(
            run_id,
            demo_enabled=launch_profile is not None,
        )
        _launch_onboarding_process(
            site=record.site,
            source_root_arg=str(source_root.resolve()),
            generated_root_arg=record.generated_root,
            runtime_root_arg=record.runtime_root,
            run_id=record.run_id,
            preview_url=preview_url or None,
            demo_enabled=launch_profile is not None,
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
            "retrieval_status": {},
            "enabled_retrieval_corpora": [],
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


def _port_in_use(port: int, *, host: str = "127.0.0.1") -> bool:
    return _probe_tcp_port(port, host=host)


def _service_bind_port(spec: ServiceLaunchSpec) -> int | None:
    if spec.healthcheck_port is not None:
        return spec.healthcheck_port
    for candidate in (spec.healthcheck_url, spec.url):
        raw = str(candidate or "").strip()
        if not raw:
            continue
        parsed = urllib.parse.urlparse(raw)
        if parsed.port is not None:
            return int(parsed.port)
    return None


def _release_bound_port(*, port: int, label: str, protected_pids: set[int]) -> str | None:
    if port <= 0 or not _port_in_use(port):
        return None
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=_subprocess_creationflags(),
        )
    except FileNotFoundError:
        return f"{label} could not inspect port {port}: lsof not found"
    except subprocess.TimeoutExpired:
        return f"{label} could not inspect port {port}: lsof timed out"

    pids = [
        token
        for token in str(result.stdout or "").splitlines()
        if token.strip().isdigit() and int(token.strip()) not in protected_pids
    ]
    if not pids:
        return f"{label} port {port} is already in use"

    try:
        subprocess.run(
            ["kill", "-TERM", *pids],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=_subprocess_creationflags(),
        )
    except FileNotFoundError:
        return f"{label} could not stop process on port {port}: kill not found"
    except subprocess.TimeoutExpired:
        return f"{label} could not stop process on port {port}: kill timed out"

    for _ in range(10):
        if not _port_in_use(port):
            return None
        time.sleep(0.2)
    return f"{label} port {port} is already in use"


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
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
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
    if diagnostics:
        snapshot.update(diagnostics)
    return snapshot


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
        diagnostics=synced.diagnostics,
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
        diagnostics=dict(spec.diagnostics),
    )


def _prepare_service_launch(spec: ServiceLaunchSpec) -> str | None:
    prepare_command = list(spec.prepare_command or [])
    if not prepare_command:
        return None

    sentinel = str(spec.prepare_sentinel or "").strip()
    if sentinel and (spec.working_directory / sentinel).exists():
        return None

    env = _build_child_env(extra=spec.env_overrides)
    try:
        result = subprocess.run(
            prepare_command,
            cwd=str(spec.working_directory),
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
            check=False,
            creationflags=_subprocess_creationflags(),
        )
    except FileNotFoundError:
        return f"{spec.label} preparation command not found: {prepare_command[0]}"
    except subprocess.TimeoutExpired:
        return f"{spec.label} preparation timed out"

    if result.returncode == 0:
        return None
    output = str(result.stderr or result.stdout or "").strip()
    return output or f"{spec.label} preparation failed"


def _ensure_service_process(*, site: str, run_id: str, spec: ServiceLaunchSpec) -> dict[str, Any]:
    key = _service_key(site, spec.service_name)
    with _REGISTRY_LOCK:
        existing = _SERVICE_REGISTRY.get(key)
        protected_pids = {os.getpid()}
        if existing is not None:
            synced = _sync_service_record(existing)
            protected_pids.add(synced.process.pid)
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
                    diagnostics=spec.diagnostics,
                )
            _terminate_service(synced)
        bind_port = _service_bind_port(spec)
        if bind_port is not None:
            port_failure = _release_bound_port(
                port=bind_port,
                label=spec.label,
                protected_pids=protected_pids,
            )
            if port_failure:
                return _service_snapshot(
                    spec.service_name,
                    spec.label,
                    run_id=run_id,
                    status="blocked",
                    reason=port_failure,
                    url=spec.url,
                    working_directory=str(spec.working_directory),
                    command=spec.command,
                    diagnostics=spec.diagnostics,
                )
        prepare_failure = _prepare_service_launch(spec)
        if prepare_failure:
            return _service_snapshot(
                spec.service_name,
                spec.label,
                run_id=run_id,
                status="blocked",
                reason=prepare_failure,
                url=spec.url,
                working_directory=str(spec.working_directory),
                command=spec.command,
                diagnostics=spec.diagnostics,
            )
        record = _launch_service(site=site, run_id=run_id, spec=spec)
        _SERVICE_REGISTRY[key] = record
        return _snapshot_from_service_record(record) or _service_snapshot(
            spec.service_name,
            spec.label,
            run_id=run_id,
            status="starting",
            url=spec.url,
            diagnostics=spec.diagnostics,
        )


def _launch_profile_labels(profile: KnownLaunchProfile) -> dict[str, str]:
    return {
        "chatbot": "Chatbot server",
        "backend": f"{profile.label} backend",
        "frontend": f"{profile.label} frontend",
    }


def _blocked_launch_snapshots(
    profile: KnownLaunchProfile,
    *,
    run_id: str,
    reason: str,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    labels = _launch_profile_labels(profile)
    return [
        _service_snapshot(
            service_name=name,
            label=labels[name],
            run_id=run_id,
            status="blocked",
            reason=reason,
            url=(
                profile.chatbot_url
                if name == "chatbot"
                else profile.backend_url if name == "backend" else profile.frontend_url
            ),
            diagnostics=diagnostics,
        )
        for name in DEMO_SERVICE_NAMES
    ]


def _bootstrap_launch_profile(profile: KnownLaunchProfile) -> dict[str, Any]:
    bootstrap = profile.bootstrap
    if bootstrap is None:
        return {"status": "skipped", "ready": True, "reason": "", "wait_target": ""}
    compose_path = ROOT / "docker" / "AWS" / "docker-compose.yml"
    if not compose_path.exists():
        return {
            "status": "failed",
            "ready": False,
            "reason": f"자동 실행 환경 파일을 찾을 수 없습니다: {compose_path}",
            "wait_target": str(bootstrap.wait_target or ""),
        }
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_path),
                "up",
                "-d",
                bootstrap.compose_service,
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "failed", "ready": False, "reason": "docker compose를 찾을 수 없습니다.", "wait_target": ""}
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "ready": False,
            "reason": f"{profile.label} 자동 실행 환경 준비 시간이 초과되었습니다.",
            "wait_target": str(bootstrap.wait_target or ""),
        }
    if result.returncode != 0:
        output = str(result.stderr or result.stdout or "").strip()
        return {
            "status": "failed",
            "ready": False,
            "reason": output or f"{profile.label} 자동 실행 환경 준비에 실패했습니다.",
            "wait_target": str(bootstrap.wait_target or ""),
        }

    wait_strategy = str(bootstrap.wait_strategy or "").strip()
    wait_target = str(bootstrap.wait_target or "").strip()
    if not wait_strategy or not wait_target:
        return {"status": "ready", "ready": True, "reason": "", "wait_target": wait_target}

    deadline = time.monotonic() + max(int(bootstrap.timeout_seconds), 1)
    while time.monotonic() < deadline:
        if wait_strategy == "tcp_port":
            host, _, port_raw = wait_target.partition(":")
            port = int(port_raw or "0")
            if port and _probe_tcp_port(port, host=host or "127.0.0.1"):
                return {"status": "ready", "ready": True, "reason": "", "wait_target": wait_target}
        elif wait_strategy == "http_url":
            if _probe_http_url(wait_target):
                return {"status": "ready", "ready": True, "reason": "", "wait_target": wait_target}
        else:
            return {
                "status": "failed",
                "ready": False,
                "reason": f"Unsupported bootstrap wait strategy: {wait_strategy}",
                "wait_target": wait_target,
            }
        time.sleep(0.5)

    return {
        "status": "failed",
        "ready": False,
        "reason": f"{profile.label} bootstrap readiness timed out",
        "wait_target": wait_target,
    }
def _build_launch_render_context(
    *,
    profile: KnownLaunchProfile,
    service_root: Path,
    chatbot_root: Path,
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
) -> dict[str, str]:
    normalized_corpora = [
        str(item).strip()
        for item in (enabled_retrieval_corpora or [])
        if str(item).strip()
    ]
    context = {
        "python": sys.executable,
        "backend_url": profile.backend_url,
        "frontend_url": profile.frontend_url,
        "chatbot_url": profile.chatbot_url.rstrip("/"),
        "service_root": str(service_root.resolve()),
        "chatbot_root": str(chatbot_root.resolve()),
        "capability_profile": str(capability_profile or "").strip(),
        "enabled_retrieval_corpora_csv": ",".join(normalized_corpora),
    }
    context["frontend_api_base"] = _render_launch_value(profile.frontend_api_base_template, context)
    return context


def _service_spec_from_profile(
    *,
    service_name: str,
    label: str,
    url: str,
    root: Path,
    launch_profile: KnownLaunchProfile,
    profile: LaunchServiceProfile | None,
    chatbot_root: Path,
    diagnostics: dict[str, Any],
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
) -> tuple[ServiceLaunchSpec | None, dict[str, Any] | None]:
    if profile is None:
        return None, None

    service_root = (root / profile.relative_root).resolve()
    required_path = service_root / profile.required_path
    if not required_path.exists():
        return None, _service_snapshot(
            service_name,
            label,
            run_id="",
            status="blocked",
            reason=f"{required_path} not found",
            url=url,
            working_directory=str(service_root),
            diagnostics=diagnostics,
        )

    context = _build_launch_render_context(
        profile=launch_profile,
        service_root=service_root,
        chatbot_root=chatbot_root,
        capability_profile=capability_profile,
        enabled_retrieval_corpora=enabled_retrieval_corpora,
    )
    return (
        ServiceLaunchSpec(
            service_name=service_name,
            label=label,
            working_directory=service_root,
            command=[_render_launch_value(token, context) for token in profile.command],
            url=url,
            healthcheck_url=(
                _render_launch_value(profile.healthcheck_url, context) if profile.healthcheck_url else None
            ),
            healthcheck_port=profile.healthcheck_port,
            env_overrides=_render_launch_values(profile.env_overrides, context),
            prepare_command=(
                [_render_launch_value(token, context) for token in profile.prepare_command]
                if profile.prepare_command
                else None
            ),
            prepare_sentinel=profile.prepare_sentinel,
            diagnostics=diagnostics,
        ),
        None,
    )


def _site_service_specs(
    *,
    profile: KnownLaunchProfile,
    host_root: Path,
    chatbot_root: Path,
    diagnostics: dict[str, Any],
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    labels = _launch_profile_labels(profile)
    service_inputs = (
        ("chatbot", chatbot_root, profile.chatbot, profile.chatbot_url),
        ("backend", host_root, profile.backend, profile.backend_url),
        ("frontend", host_root, profile.frontend, profile.frontend_url),
    )
    specs: list[ServiceLaunchSpec] = []
    blocked: list[dict[str, Any]] = []
    for service_name, root, service_profile, url in service_inputs:
        spec, blocked_snapshot = _service_spec_from_profile(
            service_name=service_name,
            label=labels[service_name],
            url=url,
            root=root,
            launch_profile=profile,
            profile=service_profile,
            chatbot_root=chatbot_root,
            diagnostics=diagnostics,
            capability_profile=capability_profile,
            enabled_retrieval_corpora=enabled_retrieval_corpora,
        )
        if blocked_snapshot is not None:
            blocked.append(blocked_snapshot)
        elif spec is not None:
            specs.append(spec)
    return specs, blocked


def _bilyeo_service_specs(*, profile: KnownLaunchProfile, source_root: Path) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    return _site_service_specs(
        profile=profile,
        host_root=source_root,
        chatbot_root=(ROOT / "chatbot").resolve(),
        diagnostics={},
    )


def _food_service_specs(*, profile: KnownLaunchProfile, source_root: Path) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    return _site_service_specs(
        profile=profile,
        host_root=source_root,
        chatbot_root=(ROOT / "chatbot").resolve(),
        diagnostics={},
    )


def _ecommerce_service_specs(*, profile: KnownLaunchProfile, source_root: Path) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    return _site_service_specs(
        profile=profile,
        host_root=source_root,
        chatbot_root=(ROOT / "chatbot").resolve(),
        diagnostics={},
    )


def _build_demo_service_specs(
    *,
    site: str,
    run_id: str,
    host_root: Path,
    chatbot_root: Path,
    preview_url: str,
    launch_profile: KnownLaunchProfile | None = None,
    diagnostics: dict[str, Any] | None = None,
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
) -> tuple[list[ServiceLaunchSpec], list[dict[str, Any]]]:
    profile = launch_profile or _resolve_launch_profile(site=site, source_root=host_root)
    if profile is None:
        return [], []
    combined_diagnostics = dict(diagnostics or {})
    bootstrap_result = _bootstrap_launch_profile(profile)
    combined_diagnostics.setdefault("bootstrap_status", bootstrap_result["status"])
    combined_diagnostics.setdefault("bootstrap_wait_target", bootstrap_result["wait_target"])
    if not bootstrap_result["ready"]:
        return [], _blocked_launch_snapshots(
            profile,
            run_id=run_id,
            reason=str(bootstrap_result["reason"] or "자동 실행 환경 준비에 실패했습니다."),
            diagnostics=combined_diagnostics,
        )

    specs, blocked = _site_service_specs(
        profile=profile,
        host_root=host_root,
        chatbot_root=chatbot_root,
        diagnostics=combined_diagnostics,
        capability_profile=capability_profile,
        enabled_retrieval_corpora=enabled_retrieval_corpora,
    )

    normalized_blocked = [
        {
            **item,
            "run_id": run_id,
            "url": item.get("url") or preview_url,
        }
        for item in blocked
    ]
    return specs, normalized_blocked


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


def _build_demo_payload(
    *,
    run_payload: dict[str, Any],
    service_snapshots: list[dict[str, Any]],
    preview_url: str,
    launch_profile: KnownLaunchProfile | None = None,
) -> dict[str, Any]:
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
    exported = str((run_payload.get("run") or {}).get("status") or "").strip() == "exported"
    normalized_preview_url = str(preview_url or "").strip()
    launch_supported = launch_profile is not None or bool(ordered_services)
    launch_status = "idle"
    launch_label = "자동 실행 대기"
    blocked_reason = str(blocked_services[0].get("reason") or "").strip() if blocked_services else ""
    validation_details = dict(((run_payload.get("details") or {}).get("validation") or {}))
    real_login_available = bool(validation_details.get("real_login_available"))
    bridge_fallback_used = bool(validation_details.get("bridge_fallback_used"))
    retrieval_status = dict(((run_payload.get("run") or {}).get("retrieval_status") or {}))
    enabled_retrieval_corpora = list((run_payload.get("run") or {}).get("enabled_retrieval_corpora") or [])
    missing_retrieval_corpora = [
        corpus
        for corpus, payload in retrieval_status.items()
        if corpus not in enabled_retrieval_corpora
        and str((payload or {}).get("status") or "").strip() not in {"completed", "enabled"}
    ]
    validation_warning_summary = str(validation_details.get("validation_warning_summary") or "").strip() or None
    demo_auth = dict(validation_details.get("demo_auth") or {})

    if validation_passed and not launch_supported:
        status = "disabled"
        status_label = "자동 실행 없음"
        message = "이 프로젝트 계열은 자동 실행 프로필이 아직 없습니다."
    elif validation_passed and blocked_services:
        status = "blocked"
        status_label = f"{launch_profile.label if launch_profile is not None else 'Site'} blocked"
        message = blocked_reason or "자동 실행 환경 준비에 실패했습니다."
        launch_status = "blocked"
        launch_label = "자동 실행 불가"
    elif validation_passed and total_count and ready_count == total_count:
        status = "ready"
        status_label = f"{launch_profile.label if launch_profile is not None else 'Site'} ready"
        message = "검증이 끝났고 사이트가 준비되었습니다."
        launch_status = "ready"
        launch_label = "사이트 열기 가능"
    elif validation_passed and any(item.get("running") for item in ordered_services):
        status = "starting"
        status_label = f"{launch_profile.label if launch_profile is not None else 'Site'} launching"
        message = "검증이 끝나 사이트를 준비하는 중입니다."
        launch_status = "launching"
        launch_label = "사이트 준비 중"
    elif validation_passed:
        status = "pending"
        status_label = "Validated"
        message = "검증이 끝났고 자동 실행을 시작할 준비가 되었습니다."
        launch_status = "launching"
        launch_label = "사이트 준비 중"
    elif (run_payload.get("run") or {}).get("status") in {"failed", "failed_human_review", "process_failed"}:
        status = "failed"
        status_label = "자동 실행 보류"
        message = "검증을 통과해야 사이트를 자동으로 시작할 수 있습니다."
        launch_status = "idle"
        launch_label = "자동 실행 대기"
    else:
        status = "pending"
        status_label = "Waiting for validation"
        message = "검증 통과 후 자동 실행을 시작합니다."
        launch_status = "idle"
        launch_label = "자동 실행 대기"

    primary_action = (
        {
            "label": "사이트 열기",
            "url": normalized_preview_url,
        }
        if launch_status == "ready" and normalized_preview_url
        else None
    )
    diagnostic_source = next((item for item in ordered_services if item), {})

    return {
        "status": status,
        "status_label": status_label,
        "message": message,
        "ready": status == "ready",
        "preview_url": preview_url,
        "launch_status": launch_status,
        "launch_label": launch_label,
        "open_url": normalized_preview_url if launch_status == "ready" else None,
        "blocked_reason": blocked_reason or None,
        "primary_action": primary_action,
        "preview_source_kind": diagnostic_source.get("preview_source_kind"),
        "preview_host_root": diagnostic_source.get("preview_host_root"),
        "preview_chatbot_root": diagnostic_source.get("preview_chatbot_root"),
        "bootstrap_status": diagnostic_source.get("bootstrap_status"),
        "bootstrap_wait_target": diagnostic_source.get("bootstrap_wait_target"),
        "real_login_available": real_login_available,
        "bridge_fallback_used": bridge_fallback_used,
        "enabled_retrieval_corpora": enabled_retrieval_corpora,
        "missing_retrieval_corpora": missing_retrieval_corpora,
        "validation_warning_summary": validation_warning_summary,
        "demo_auth": demo_auth,
        "services": ordered_services,
    }


def _build_disabled_demo_payload(*, message: str = GITHUB_MODE_MESSAGE) -> dict[str, Any]:
    return {
        "status": "disabled",
        "status_label": "자동 실행 없음",
        "message": message,
        "ready": False,
        "preview_url": None,
        "launch_status": "idle",
        "launch_label": "자동 실행 대기",
        "open_url": None,
        "blocked_reason": None,
        "primary_action": None,
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


def _ensure_demo_services(
    *,
    site: str,
    run_id: str,
    run_root: Path | None = None,
    run_payload: dict[str, Any],
    preview_url: str,
) -> list[dict[str, Any]]:
    details = run_payload.get("details") or {}
    validation_details = details.get("validation") or {}
    launch_profile = _launch_profile_from_run(site=site, run_id=run_id, run_payload=run_payload)

    if not bool(validation_details.get("passed")):
        return _collect_service_snapshots(site=site, run_id=run_id)

    effective_run_root = run_root
    if effective_run_root is None:
        record = _lookup_record(site, run_id)
        if record is not None:
            effective_run_root = _run_root_from_record(record)
    selection = _resolve_preview_workspace_selection(
        run_root=effective_run_root or Path(),
        run_payload=run_payload,
    )
    capability_profile = str((run_payload.get("run") or {}).get("final_capability_profile") or "").strip()
    enabled_retrieval_corpora = [
        str(item).strip()
        for item in list((run_payload.get("run") or {}).get("enabled_retrieval_corpora") or [])
        if str(item).strip()
    ]
    diagnostics = {
        "preview_source_kind": selection.source_kind,
        "preview_host_root": str(selection.host_root),
        "preview_chatbot_root": str(selection.chatbot_root),
    }

    if not selection.host_root.exists():
        profile = launch_profile or KnownLaunchProfile(
            site=site,
            label=site.title() or "Site",
            preview_url=preview_url,
            backend_url="http://127.0.0.1:8000",
            frontend_url=preview_url,
        )
        return [
            _service_snapshot(
                "backend",
                f"{profile.label} backend",
                run_id=run_id,
                status="blocked",
                reason=f"host preview root not found: {selection.host_root}",
                url=profile.backend_url,
                diagnostics=diagnostics,
            ),
            _service_snapshot(
                "chatbot",
                "Chatbot server",
                run_id=run_id,
                status="blocked",
                reason=f"chatbot preview root not found: {selection.chatbot_root}",
                url=profile.chatbot_url,
                diagnostics=diagnostics,
            ),
            _service_snapshot(
                "frontend",
                f"{profile.label} frontend",
                run_id=run_id,
                status="blocked",
                reason=f"host preview root not found: {selection.host_root}",
                url=preview_url,
                diagnostics=diagnostics,
            ),
        ]
    specs, blocked = _build_demo_service_specs(
        site=site,
        run_id=run_id,
        host_root=selection.host_root,
        chatbot_root=selection.chatbot_root,
        preview_url=preview_url,
        launch_profile=launch_profile,
        diagnostics=diagnostics,
        capability_profile=capability_profile,
        enabled_retrieval_corpora=enabled_retrieval_corpora,
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
def index() -> HTMLResponse:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace(STATIC_ASSET_VERSION_TOKEN, _static_asset_version()))


def _static_asset_version() -> str:
    relevant_paths = [
        STATIC_ROOT / "index.html",
        STATIC_ROOT / "app.js",
        STATIC_ROOT / "styles.css",
    ]
    latest_mtime_ns = 0
    for path in relevant_paths:
        try:
            latest_mtime_ns = max(latest_mtime_ns, path.stat().st_mtime_ns)
        except OSError:
            continue
    return format(latest_mtime_ns or int(time.time_ns()), "x")


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
async def create_github_import(http_request: Request) -> dict[str, object]:
    _cleanup_expired_github_imports()
    content_type = str(http_request.headers.get("content-type") or "").lower()
    repo_url = ""
    env_target_path = ""
    env_file_name = ""
    env_file_content = b""
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await http_request.form()
        repo_url = str(form.get("repo_url") or "").strip()
        env_target_path = _normalize_github_env_target_path(form.get("env_target_path") or ".env")
        env_file = form.get("env_file")
        if hasattr(env_file, "filename") and hasattr(env_file, "read"):
            env_file_name = str(getattr(env_file, "filename", "") or "").strip()
            env_file_content = await env_file.read()
            close = getattr(env_file, "close", None)
            if callable(close):
                await close()
        elif env_file not in (None, ""):
            raise HTTPException(status_code=400, detail="Invalid env file upload")
        if env_file_name and not env_file_content:
            raise HTTPException(status_code=400, detail="Uploaded env file is empty")
        if not env_file_name:
            env_target_path = ""
    else:
        try:
            payload = GitHubImportRequest.model_validate(await http_request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid GitHub import request") from exc
        repo_url = payload.repo_url.strip()
        env_target_path = _normalize_github_env_target_path(payload.env_target_path)
    try:
        repo_probe = _probe_github_repository(repo_url)
    except GitHubImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import_run = _store_github_import_run(_new_github_import_run(repo_probe=repo_probe))
    if env_file_name:
        import_run = _store_github_import_run(
            _store_github_import_env_attachment(
                record=import_run,
                filename=env_file_name,
                content=env_file_content,
                target_path=env_target_path or ".env",
            )
        )
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
    payload = decorate_dashboard_payload(payload)
    github_mode = _github_mode_enabled_for_run(site=site, run_id=run_id, process_record=process_record)
    if github_mode:
        payload["services"] = []
        payload["demo"] = _build_disabled_demo_payload()
        return payload

    launch_profile = _launch_profile_from_run(site=site, run_id=run_id, run_payload=payload)
    preview_url = (
        (process.preview_url if process is not None else None)
        or str((payload.get("process") or {}).get("preview_url") or "").strip()
        or _launch_profile_preview_url(launch_profile)
    )
    services = _ensure_demo_services(
        site=site,
        run_id=run_id,
        run_root=run_root,
        run_payload=payload,
        preview_url=preview_url,
    )
    payload["services"] = services
    payload["demo"] = _build_demo_payload(
        run_payload=payload,
        service_snapshots=services,
        preview_url=preview_url,
        launch_profile=launch_profile,
    )
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("onmo.app:app", host="127.0.0.1", port=8899, reload=_onmo_reload_enabled())
