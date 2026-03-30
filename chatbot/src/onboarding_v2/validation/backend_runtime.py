from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from chatbot.src.onboarding.runtime_completion_runner import _probe_http_ready, _terminate_process
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimeCommandResult,
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
)

ValidationEventCallback = Callable[[dict[str, Any]], None]

_ORACLE_REQUIRED_ENV_KEYS = [
    "ORACLE_USER",
    "ORACLE_PASSWORD",
    "ORACLE_HOST",
    "ORACLE_PORT",
    "ORACLE_SERVICE_NAME",
]
_EXTERNAL_DEPENDENCY_ERROR_TOKENS = (
    "socket.gaierror",
    "nodename nor servname provided",
    "name or service not known",
    "temporary failure in name resolution",
    "could not translate host name",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "unable to connect",
    "can't connect",
    "connection aborted",
    "connection error",
    "dpy-",
    "ora-",
)


def _loaded_env_source_labels(env_source: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for label in ("source", "backend", "workspace"):
        if bool(env_source.get(f"loaded_{label}_dotenv")):
            labels.append(label)
    return labels


def _classify_dependency_kind(*, output_text: str, env: dict[str, str], script_path: Path | None) -> str | None:
    lower_output = output_text.lower()
    lower_script = str(script_path or "").lower()
    oracle_markers = (
        "oracledb",
        "oracle",
        "dpy-",
        "ora-",
    )
    if any(marker in lower_output for marker in oracle_markers):
        return "oracle"
    if any(str(key).startswith("ORACLE_") for key in env):
        return "oracle"
    if "oracle" in lower_script:
        return "oracle"
    return None


def _required_env_keys_for_dependency_kind(kind: str | None) -> list[str]:
    if kind == "oracle":
        return list(_ORACLE_REQUIRED_ENV_KEYS)
    return []


def _should_defer_fixture_scripts(
    *,
    env: dict[str, str],
    reset_path: Path | None,
    seed_path: Path | None,
) -> tuple[bool, str | None]:
    if reset_path is None and seed_path is None:
        return False, None
    dependency_kind = _classify_dependency_kind(
        output_text="",
        env=env,
        script_path=reset_path or seed_path,
    )
    required_env_keys = _required_env_keys_for_dependency_kind(dependency_kind)
    has_all_required_env = all(str(env.get(key) or "").strip() for key in required_env_keys)
    return dependency_kind == "oracle" and has_all_required_env, dependency_kind


def _classify_prep_external_dependency_failure(
    *,
    step_name: str,
    result: BackendRuntimeCommandResult,
    env: dict[str, str],
    env_source: dict[str, Any],
    script_path: Path | None,
) -> dict[str, Any] | None:
    output_text = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if str(part or "").strip()
    )
    lower_output = output_text.lower()
    dependency_kind = _classify_dependency_kind(
        output_text=output_text,
        env=env,
        script_path=script_path,
    )
    required_env_keys = _required_env_keys_for_dependency_kind(dependency_kind)
    missing_env_keys = [key for key in required_env_keys if not str(env.get(key) or "").strip()]
    has_external_dependency_signal = any(
        token in lower_output for token in _EXTERNAL_DEPENDENCY_ERROR_TOKENS
    )
    if not has_external_dependency_signal and not missing_env_keys:
        return None
    diagnostics: dict[str, Any] = {
        "step_name": step_name,
        "script_path": str(script_path) if script_path is not None else None,
        "loaded_env_sources": _loaded_env_source_labels(env_source),
        "missing_env_keys": missing_env_keys,
        "error_excerpt": output_text[:2000],
    }
    if result.returncode not in (None, 0):
        diagnostics["returncode"] = result.returncode
    if dependency_kind is not None:
        diagnostics["dependency_kind"] = dependency_kind
    return {
        "failure_origin": "host_contract",
        "failure_code": "backend_runtime_prep_external_dependency_unavailable",
        "dependency_kind": dependency_kind,
        "required_env_keys": required_env_keys,
        "dependency_diagnostics": diagnostics,
    }


def prepare_backend_runtime(
    *,
    workspace: str | Path,
    snapshot: AnalysisSnapshot,
    live_logs_root: str | Path | None = None,
    event_callback: ValidationEventCallback | None = None,
    heartbeat_interval_s: float = 5.0,
) -> BackendRuntimePrepResult:
    workspace = Path(workspace).resolve()
    backend_root = _resolve_backend_root(workspace)
    source_root = Path(snapshot.repo_profile.source_root).resolve()
    backend_env_defaults, env_source = _load_backend_env_defaults(
        backend_root,
        source_root=source_root,
    )
    framework = snapshot.repo_profile.backend_framework
    runtime_root = _resolve_validation_support_root(workspace)
    live_logs_root_path = (
        Path(live_logs_root).resolve() if live_logs_root is not None else None
    )
    if live_logs_root_path is not None:
        live_logs_root_path.mkdir(parents=True, exist_ok=True)
    venv_path = runtime_root / "venv"
    python_executable = _venv_python(venv_path)
    runtime_root.mkdir(parents=True, exist_ok=True)
    live_log_paths: dict[str, str] = {}

    create_venv = _run_prep_step(
        step_name="venv",
        command_preview=[sys.executable, "-m", "venv", str(venv_path)],
        cwd=venv_path.parent,
        command_factory=lambda log_path: _create_venv(
            sys.executable,
            venv_path,
            log_path=log_path,
            heartbeat_interval_s=heartbeat_interval_s,
            progress_callback=_step_progress_emitter(
                event_callback,
                step_name="venv",
                command=[sys.executable, "-m", "venv", str(venv_path)],
                cwd=venv_path.parent,
                log_path=log_path,
            ),
        ),
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _record_live_log_path(live_log_paths, "venv", create_venv.log_path)
    if not create_venv.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=_prep_failure_summary("venv", create_venv),
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            env_source=env_source,
            live_log_paths=live_log_paths,
            related_files=_default_related_files(framework),
        )

    install = _run_prep_step(
        step_name="install",
        command_preview=[
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(backend_root / "requirements.txt"),
        ],
        cwd=backend_root,
        command_factory=lambda log_path: _install_backend_requirements(
            backend_root=backend_root,
            python_executable=python_executable,
            log_path=log_path,
            heartbeat_interval_s=heartbeat_interval_s,
            progress_callback=_step_progress_emitter(
                event_callback,
                step_name="install",
                command=[
                    str(python_executable),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-r",
                    str(backend_root / "requirements.txt"),
                ],
                cwd=backend_root,
                log_path=log_path,
            ),
        ),
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _record_live_log_path(live_log_paths, "install", install.log_path)
    if not install.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=_prep_failure_summary("install", install),
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            env_source=env_source,
            live_log_paths=live_log_paths,
            related_files=_default_related_files(framework),
        )

    migrate = _run_prep_step(
        step_name="migrate",
        command_preview=[str(python_executable), "manage.py", "migrate", "--noinput"],
        cwd=backend_root,
        command_factory=lambda log_path: _run_django_migrate(
            framework=framework,
            backend_root=backend_root,
            python_executable=python_executable,
            env=build_backend_subprocess_env(
                backend_root=backend_root,
                dotenv_defaults=backend_env_defaults,
            ),
            log_path=log_path,
            heartbeat_interval_s=heartbeat_interval_s,
            progress_callback=_step_progress_emitter(
                event_callback,
                step_name="migrate",
                command=[str(python_executable), "manage.py", "migrate", "--noinput"],
                cwd=backend_root,
                log_path=log_path,
            ),
        ),
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _record_live_log_path(live_log_paths, "migrate", migrate.log_path)
    if not migrate.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=_prep_failure_summary("migrate", migrate),
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            env_source=env_source,
            live_log_paths=live_log_paths,
            fixture_manifest=_build_fixture_manifest(
                available=False,
                seed_source={},
                reason=_prep_failure_summary("migrate", migrate),
            ),
            related_files=_default_related_files(framework),
        )

    reset_path = _discover_reset_script(workspace=workspace, backend_root=backend_root)
    seed_path = _discover_seed_script(workspace=workspace, backend_root=backend_root)
    reset_env = build_backend_subprocess_env(
        backend_root=backend_root,
        dotenv_defaults=backend_env_defaults,
    )
    defer_fixture_scripts, deferred_dependency_kind = _should_defer_fixture_scripts(
        env=reset_env,
        reset_path=reset_path,
        seed_path=seed_path,
    )
    reset_command = [str(python_executable), str(reset_path)] if reset_path is not None else []
    reset = _run_prep_step(
        step_name="reset",
        command_preview=reset_command,
        cwd=backend_root,
        command_factory=lambda log_path: _skipped_command_result(
            name="reset",
            command=reset_command,
            cwd=backend_root,
            stdout="reset deferred until runtime fixture discovery",
            skipped_reason="oracle reset deferred until runtime order probe",
            log_path=log_path,
        )
        if defer_fixture_scripts
        else _run_optional_script(
            name="reset",
            script_path=reset_path,
            framework=framework,
            backend_root=backend_root,
            python_executable=python_executable,
            env=reset_env,
            missing_stdout="reset script not found; skipped reset",
            log_path=log_path,
            heartbeat_interval_s=heartbeat_interval_s,
            progress_callback=_step_progress_emitter(
                event_callback,
                step_name="reset",
                command=reset_command,
                cwd=backend_root,
                log_path=log_path,
            ),
        ),
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _record_live_log_path(live_log_paths, "reset", reset.log_path)
    if not reset.passed:
        failure_details = _classify_prep_external_dependency_failure(
            step_name="reset",
            result=reset,
            env=reset_env,
            env_source=env_source,
            script_path=reset_path,
        ) or {}
        fixture_manifest = _build_fixture_manifest(
            available=False,
            seed_source=_build_seed_source(
                workspace=workspace,
                reset_path=reset_path,
                seed_path=seed_path,
                python_executable=python_executable,
            ),
            reason=_prep_failure_summary("reset", reset),
        )
        for key in ("failure_origin", "failure_code", "dependency_kind", "required_env_keys", "dependency_diagnostics"):
            value = failure_details.get(key)
            if value not in (None, [], {}):
                fixture_manifest[key] = value
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=_prep_failure_summary("reset", reset),
            failure_origin=failure_details.get("failure_origin"),
            failure_code=failure_details.get("failure_code"),
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            dependency_kind=failure_details.get("dependency_kind"),
            required_env_keys=list(failure_details.get("required_env_keys") or []),
            dependency_diagnostics=dict(failure_details.get("dependency_diagnostics") or {}),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            reset=reset,
            env_source=env_source,
            live_log_paths=live_log_paths,
            seed_source_path=str(seed_path) if seed_path is not None else None,
            reset_source_path=str(reset_path) if reset_path is not None else None,
            fixture_manifest=fixture_manifest,
            related_files=_default_related_files(framework),
        )

    seed_env = build_backend_subprocess_env(
        backend_root=backend_root,
        dotenv_defaults=backend_env_defaults,
    )
    seed_command = [str(python_executable), str(seed_path)] if seed_path is not None else []
    seed = _run_prep_step(
        step_name="seed",
        command_preview=seed_command,
        cwd=backend_root,
        command_factory=lambda log_path: _skipped_command_result(
            name="seed",
            command=seed_command,
            cwd=backend_root,
            stdout="seed deferred until runtime fixture discovery",
            skipped_reason="oracle seed deferred until runtime order probe",
            log_path=log_path,
        )
        if defer_fixture_scripts
        else _run_optional_script(
            name="seed",
            script_path=seed_path,
            framework=framework,
            backend_root=backend_root,
            python_executable=python_executable,
            env=seed_env,
            missing_stdout="seed script not found; skipped seed",
            log_path=log_path,
            heartbeat_interval_s=heartbeat_interval_s,
            progress_callback=_step_progress_emitter(
                event_callback,
                step_name="seed",
                command=seed_command,
                cwd=backend_root,
                log_path=log_path,
            ),
        ),
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _record_live_log_path(live_log_paths, "seed", seed.log_path)
    if not seed.passed:
        failure_details = _classify_prep_external_dependency_failure(
            step_name="seed",
            result=seed,
            env=seed_env,
            env_source=env_source,
            script_path=seed_path,
        ) or {}
        fixture_manifest = _build_fixture_manifest(
            available=False,
            seed_source=_build_seed_source(
                workspace=workspace,
                reset_path=reset_path,
                seed_path=seed_path,
                python_executable=python_executable,
            ),
            reason=_prep_failure_summary("seed", seed),
        )
        for key in ("failure_origin", "failure_code", "dependency_kind", "required_env_keys", "dependency_diagnostics"):
            value = failure_details.get(key)
            if value not in (None, [], {}):
                fixture_manifest[key] = value
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=_prep_failure_summary("seed", seed),
            failure_origin=failure_details.get("failure_origin"),
            failure_code=failure_details.get("failure_code"),
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            dependency_kind=failure_details.get("dependency_kind"),
            required_env_keys=list(failure_details.get("required_env_keys") or []),
            dependency_diagnostics=dict(failure_details.get("dependency_diagnostics") or {}),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            reset=reset,
            seed=seed,
            env_source=env_source,
            live_log_paths=live_log_paths,
            seed_source_path=str(seed_path) if seed_path is not None else None,
            reset_source_path=str(reset_path) if reset_path is not None else None,
            fixture_manifest=fixture_manifest,
            related_files=_default_related_files(framework),
        )

    fixture_manifest_log_path = _step_log_path(live_logs_root_path, "fixture_manifest")
    _emit_step_event(
        event_callback,
        step_name="fixture_manifest",
        phase_kind="start",
        command=[],
        cwd=backend_root,
        log_path=fixture_manifest_log_path,
        status="running",
    )
    fixture_manifest = _build_fixture_manifest(
        available=(seed_path is not None and not seed.skipped) if not defer_fixture_scripts else False,
        seed_source=_build_seed_source(
            workspace=workspace,
            reset_path=reset_path,
            seed_path=seed_path,
            python_executable=python_executable,
        ),
        reason=(
            None
            if seed_path is not None and not seed.skipped
            else "fixture_unavailable"
        )
        if not defer_fixture_scripts
        else "runtime_fixture_discovery_pending",
    )
    if defer_fixture_scripts:
        fixture_manifest["deferred_seed_strategy"] = "runtime_order_probe"
        if deferred_dependency_kind:
            fixture_manifest["dependency_kind"] = deferred_dependency_kind
    if fixture_manifest_log_path is not None:
        fixture_manifest_log_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_manifest_log_path.write_text(
            json.dumps(fixture_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _record_live_log_path(live_log_paths, "fixture_manifest", str(fixture_manifest_log_path))
    _emit_step_event(
        event_callback,
        step_name="fixture_manifest",
        phase_kind="finish",
        command=[],
        cwd=backend_root,
        log_path=fixture_manifest_log_path,
        status="completed",
    )

    return BackendRuntimePrepResult(
        framework=framework,
        passed=True,
        failure_summary="backend runtime prepared",
        backend_root=str(backend_root),
        venv_path=str(venv_path),
        python_executable=str(python_executable),
        create_venv=create_venv,
        install=install,
        migrate=migrate,
        reset=reset,
        seed=seed,
        seed_source_path=str(seed_path) if seed_path is not None else None,
        reset_source_path=str(reset_path) if reset_path is not None else None,
        fixture_manifest=fixture_manifest,
        env_source=env_source,
        live_log_paths=live_log_paths,
        related_files=_default_related_files(framework),
    )


def build_backend_runtime_plan(
    *,
    workspace: str | Path,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    prep_result: BackendRuntimePrepResult,
) -> BackendRuntimePlan:
    workspace = Path(workspace).resolve()
    backend_root = _resolve_backend_root(workspace)
    framework = snapshot.repo_profile.backend_framework
    python_executable = prep_result.python_executable or sys.executable
    environment = {"PYTHONUNBUFFERED": "1", "ONBOARDING_VALIDATION": "1"}
    environment["ONBOARDING_CAPABILITY_PROFILE"] = str(
        plan.host_backend.capability_profile or "order_cs_only"
    )
    environment["ONBOARDING_ENABLED_RETRIEVAL_CORPORA"] = json.dumps(
        list(plan.host_backend.enabled_retrieval_corpora or []),
        ensure_ascii=False,
    )
    environment["ONBOARDING_WIDGET_FEATURES"] = json.dumps(
        dict(plan.host_backend.widget_features or {}),
        ensure_ascii=False,
    )
    listen_port = _allocate_free_listen_port()
    launcher_mode: str | None = None
    launcher_metadata_path: str | None = None

    if framework == "django":
        command = [python_executable, "manage.py", "runserver", f"127.0.0.1:{listen_port}"]
    elif framework == "flask":
        entrypoint = _choose_backend_entrypoint(snapshot=snapshot, backend_root=backend_root, defaults=("app.py", "run.py"))
        launcher_path, metadata_path = _write_flask_validation_launcher(
            backend_root=backend_root,
            support_root=_resolve_validation_support_root(workspace),
            entrypoint=entrypoint,
            listen_port=listen_port,
        )
        launcher_mode = "flask_validation_launcher"
        launcher_metadata_path = str(metadata_path)
        environment.update(
            {
                "ONBOARDING_VALIDATION_SKIP_DB_INIT": "1",
            }
        )
        command = [python_executable, str(launcher_path)]
    elif framework == "fastapi":
        entrypoint = _choose_backend_entrypoint(snapshot=snapshot, backend_root=backend_root, defaults=("main.py", "app.py"))
        module_name = _module_name_from_path(Path(entrypoint))
        command = [
            python_executable,
            "-m",
            "uvicorn",
            f"{module_name}:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(listen_port),
        ]
    else:
        command = [python_executable, "manage.py", "runserver", f"127.0.0.1:{listen_port}"]

    readiness_url = (
        f"http://127.0.0.1:{listen_port}" + plan.host_backend.chat_auth_contract_path
    )
    return BackendRuntimePlan(
        framework=framework,
        backend_root=str(backend_root),
        command=command,
        readiness_url=readiness_url,
        listen_port=listen_port,
        environment=environment,
        python_executable=str(python_executable),
        launcher_mode=launcher_mode,
        launcher_metadata_path=launcher_metadata_path,
    )


def launch_backend_runtime(
    plan: BackendRuntimePlan,
    *,
    log_path: str | Path | None = None,
) -> BackendRuntimeState:
    environment = build_backend_subprocess_env(
        backend_root=plan.backend_root,
        extra_env=plan.environment,
    )
    launcher_log_path = Path(log_path).resolve() if log_path is not None else None
    popen_kwargs: dict[str, Any] = {
        "cwd": plan.backend_root,
        "env": environment,
        "text": True,
    }
    log_handle = None
    if launcher_log_path is None:
        popen_kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
    else:
        launcher_log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = launcher_log_path.open("a", encoding="utf-8")
        popen_kwargs.update({"stdout": log_handle, "stderr": log_handle})
    process = subprocess.Popen(plan.command, **popen_kwargs)
    if log_handle is not None:
        log_handle.close()
    readiness = _probe_http_ready(plan.readiness_url)
    if launcher_log_path is not None:
        with launcher_log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"readiness_url": plan.readiness_url, "readiness": readiness},
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
    launcher_metadata = _read_launcher_metadata(plan.launcher_metadata_path)
    if readiness.get("passed"):
        return BackendRuntimeState(
            framework=plan.framework,
            passed=True,
            pid=process.pid,
            command=list(plan.command),
            readiness_url=plan.readiness_url,
            listen_port=plan.listen_port,
            launcher_mode=str(launcher_metadata.get("launcher_mode") or plan.launcher_mode or ""),
            startup_hooks_skipped=list(launcher_metadata.get("startup_hooks_skipped") or []),
            readiness=readiness,
            launcher_log_path=str(launcher_log_path) if launcher_log_path is not None else None,
            related_files=_default_related_files(plan.framework),
            process_handle=process,
        )

    if launcher_log_path is None:
        stdout, stderr = _collect_process_output(process)
    else:
        stdout = _read_text_if_exists(launcher_log_path)
        stderr = ""
    _terminate_process(process)
    return BackendRuntimeState(
        framework=plan.framework,
        passed=False,
        pid=process.pid,
        command=list(plan.command),
        readiness_url=plan.readiness_url,
        listen_port=plan.listen_port,
        launcher_mode=str(launcher_metadata.get("launcher_mode") or plan.launcher_mode or ""),
        startup_hooks_skipped=list(launcher_metadata.get("startup_hooks_skipped") or []),
        readiness=readiness,
        launcher_log_path=str(launcher_log_path) if launcher_log_path is not None else None,
        failure_summary=str(readiness.get("error") or "backend readiness probe failed"),
        stdout=stdout,
        stderr=stderr,
        related_files=_default_related_files(plan.framework),
    )


def stop_backend_runtime(state: BackendRuntimeState) -> None:
    process = state.process_handle
    if process is None:
        return
    _terminate_process(process)


def _resolve_backend_root(workspace: Path) -> Path:
    backend_root = workspace / "backend"
    return backend_root if backend_root.exists() else workspace


def _resolve_validation_support_root(workspace: Path) -> Path:
    workspace = workspace.resolve()
    host_root = workspace.parent if workspace.name == "backend" else workspace
    if host_root.name in {"host", "chatbot"} and host_root.parent.name == "workspace":
        return host_root.parent.parent / "validation-support" / "host-backend"
    if host_root.name == "workspace":
        return host_root.parent / "validation-support" / "host-backend"
    return host_root / "validation-support" / "host-backend"


def build_backend_subprocess_env(
    *,
    backend_root: str | Path,
    extra_env: dict[str, str] | None = None,
    dotenv_defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    backend_root_path = Path(backend_root).resolve()
    defaults = dict(dotenv_defaults or _load_backend_env_defaults(backend_root_path)[0])
    environment = {str(key): str(value) for key, value in os.environ.items()}
    for key, value in defaults.items():
        normalized_key = str(key)
        if normalized_key in environment:
            continue
        environment[normalized_key] = str(value)
    if extra_env:
        environment.update(
            {
                str(key): str(value)
                for key, value in extra_env.items()
                if value is not None
            }
        )
    return environment


def _load_backend_env_defaults(
    backend_root: Path,
    *,
    source_root: Path | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    workspace_root = backend_root.parent if backend_root.name == "backend" else backend_root
    env_source: dict[str, Any] = {
        "loaded_workspace_dotenv": False,
        "workspace_dotenv_path": None,
        "loaded_backend_dotenv": False,
        "backend_dotenv_path": None,
        "loaded_source_dotenv": False,
        "source_dotenv_path": None,
    }
    defaults: dict[str, str] = {}
    candidates: list[tuple[str, Path]] = []
    if source_root is not None:
        candidates.append(("source", source_root / ".env"))
    candidates.extend(
        (
            ("backend", backend_root / ".env"),
            ("workspace", workspace_root / ".env"),
        )
    )
    for label, path in candidates:
        if not path.exists():
            continue
        defaults.update(_parse_dotenv_file(path))
        env_source[f"loaded_{label}_dotenv"] = True
        env_source[f"{label}_dotenv_path"] = str(path)
    return defaults, env_source


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _allocate_free_listen_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _detect_flask_runtime_port(entrypoint_path: Path) -> int | None:
    try:
        module = ast.parse(entrypoint_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    resolved_names: dict[str, int] = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            resolved = _resolve_port_value(node.value, resolved_names)
            if resolved is not None:
                resolved_names[node.targets[0].id] = resolved

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "run":
            continue
        for keyword in node.keywords:
            if keyword.arg != "port":
                continue
            resolved = _resolve_port_value(keyword.value, resolved_names)
            if resolved is not None:
                return resolved
    return None


def _write_flask_validation_launcher(
    *,
    backend_root: Path,
    support_root: Path,
    entrypoint: str,
    listen_port: int,
) -> tuple[Path, Path]:
    support_root.mkdir(parents=True, exist_ok=True)
    launcher_path = support_root / "flask_validation_launcher.py"
    metadata_path = support_root / "flask_validation_launcher_metadata.json"
    script = f"""from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path({str(backend_root)!r})
ENTRYPOINT_PATH = BACKEND_ROOT / {entrypoint!r}
LISTEN_PORT = {listen_port}
METADATA_PATH = Path({str(metadata_path)!r})

os.environ.setdefault("ONBOARDING_VALIDATION", "1")
os.environ.setdefault("ONBOARDING_VALIDATION_SKIP_DB_INIT", "1")
sys.path.insert(0, str(BACKEND_ROOT))


def _noop(*args, **kwargs):
    return None


def _write_metadata(*, startup_hooks_skipped):
    METADATA_PATH.write_text(
        json.dumps(
            {{
                "launcher_mode": "flask_validation_launcher",
                "startup_hooks_skipped": list(startup_hooks_skipped),
                "listen_port": LISTEN_PORT,
                "entrypoint": str(ENTRYPOINT_PATH),
            }},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


spec = importlib.util.spec_from_file_location(
    "onboarding_validation_backend_entrypoint",
    ENTRYPOINT_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load Flask entrypoint: {{ENTRYPOINT_PATH}}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

startup_hooks_skipped = []
if os.environ.get("ONBOARDING_VALIDATION_SKIP_DB_INIT") == "1":
    for hook_name in ("init_db_with_retry", "init_db"):
        candidate = getattr(module, hook_name, None)
        if callable(candidate):
            setattr(module, hook_name, _noop)
            startup_hooks_skipped.append(hook_name)

_write_metadata(startup_hooks_skipped=startup_hooks_skipped)

create_app = getattr(module, "create_app", None)
if callable(create_app):
    app = create_app()
else:
    app = getattr(module, "app", None)

if app is None:
    raise RuntimeError("Flask entrypoint did not expose app or create_app")

app.run(host="127.0.0.1", port=LISTEN_PORT, debug=False, use_reloader=False)
"""
    launcher_path.write_text(script, encoding="utf-8")
    return launcher_path, metadata_path


def _read_launcher_metadata(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    metadata_path = Path(path)
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _resolve_port_value(node: ast.AST, resolved_names: dict[str, int]) -> int | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int):
            return node.value
        if isinstance(node.value, str) and node.value.isdigit():
            return int(node.value)
        return None

    if isinstance(node, ast.Name):
        return resolved_names.get(node.id)

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "int" and node.args:
            return _resolve_port_value(node.args[0], resolved_names)
        if _is_os_environ_get_call(node) or _is_os_getenv_call(node):
            if len(node.args) >= 2:
                return _resolve_port_value(node.args[1], resolved_names)
            for keyword in node.keywords:
                if keyword.arg == "default":
                    return _resolve_port_value(keyword.value, resolved_names)
        return None

    return None


def _is_os_environ_get_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
    )


def _is_os_getenv_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "getenv"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )


def _create_venv(
    python_executable: str,
    venv_path: Path,
    *,
    log_path: Path | None = None,
    heartbeat_interval_s: float = 5.0,
    progress_callback: ValidationEventCallback | None = None,
) -> BackendRuntimeCommandResult:
    if _venv_python(venv_path).exists():
        return _skipped_command_result(
            name="create_venv",
            command=[python_executable, "-m", "venv", str(venv_path)],
            cwd=venv_path.parent,
            stdout="existing venv reused",
            skipped_reason="existing venv reused",
            log_path=log_path,
        )
    result = _run_command(
        name="create_venv",
        command=[python_executable, "-m", "venv", str(venv_path)],
        cwd=venv_path.parent,
        log_path=log_path,
        heartbeat_interval_s=heartbeat_interval_s,
        progress_callback=progress_callback,
    )
    if result.passed:
        return result
    stderr_text = str(result.stderr or "").lower()
    if (
        _venv_python(venv_path).exists()
        and "file exists" in stderr_text
    ):
        return _skipped_command_result(
            name="create_venv",
            command=[python_executable, "-m", "venv", str(venv_path)],
            cwd=venv_path.parent,
            stdout="existing venv reused",
            skipped_reason="existing venv reused",
            log_path=log_path,
        )
    return result


def _install_backend_requirements(
    *,
    backend_root: Path,
    python_executable: Path,
    log_path: Path | None = None,
    heartbeat_interval_s: float = 5.0,
    progress_callback: ValidationEventCallback | None = None,
) -> BackendRuntimeCommandResult:
    requirements_path = backend_root / "requirements.txt"
    if not requirements_path.exists():
        return _skipped_command_result(
            name="install",
            command=[],
            cwd=backend_root,
            stdout="requirements.txt not found; skipped install",
            skipped_reason="requirements.txt not found",
            log_path=log_path,
        )
    return _run_command(
        name="install",
        command=[
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements_path),
        ],
        cwd=backend_root,
        log_path=log_path,
        heartbeat_interval_s=heartbeat_interval_s,
        progress_callback=progress_callback,
    )


def _run_django_migrate(
    *,
    framework: str,
    backend_root: Path,
    python_executable: Path,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    heartbeat_interval_s: float = 5.0,
    progress_callback: ValidationEventCallback | None = None,
) -> BackendRuntimeCommandResult:
    if framework != "django" or not (backend_root / "manage.py").exists():
        return _skipped_command_result(
            name="migrate",
            command=[],
            cwd=backend_root,
            stdout="migrate skipped",
            skipped_reason="framework does not require migrate",
            log_path=log_path,
        )
    return _run_command(
        name="migrate",
        command=[str(python_executable), "manage.py", "migrate", "--noinput"],
        cwd=backend_root,
        env=env,
        log_path=log_path,
        heartbeat_interval_s=heartbeat_interval_s,
        progress_callback=progress_callback,
    )


def _run_optional_script(
    *,
    name: str,
    script_path: Path | None,
    framework: str,
    backend_root: Path,
    python_executable: Path,
    env: dict[str, str] | None,
    missing_stdout: str,
    log_path: Path | None = None,
    heartbeat_interval_s: float = 5.0,
    progress_callback: ValidationEventCallback | None = None,
) -> BackendRuntimeCommandResult:
    del framework
    if script_path is None:
        return _skipped_command_result(
            name=name,
            command=[],
            cwd=backend_root,
            stdout=missing_stdout,
            skipped_reason=missing_stdout,
            log_path=log_path,
        )
    return _run_command(
        name=name,
        command=[str(python_executable), str(script_path)],
        cwd=backend_root,
        env=env,
        log_path=log_path,
        heartbeat_interval_s=heartbeat_interval_s,
        progress_callback=progress_callback,
        stdin_text="y\n" if name == "reset" else None,
    )


def _discover_seed_script(*, workspace: Path, backend_root: Path) -> Path | None:
    candidates = [
        backend_root / "seed" / "seed.py",
        backend_root / "scripts" / "seed.py",
        workspace / "scripts" / "seed.py",
    ]
    return _first_existing_path(candidates)


def _discover_reset_script(*, workspace: Path, backend_root: Path) -> Path | None:
    candidates = [
        backend_root / "seed" / "reset.py",
        backend_root / "scripts" / "reset_db.py",
        workspace / "scripts" / "reset_db.py",
    ]
    return _first_existing_path(candidates)


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _run_prep_step(
    *,
    step_name: str,
    command_preview: list[str],
    cwd: Path,
    command_factory: Callable[[Path | None], BackendRuntimeCommandResult],
    live_logs_root: Path | None,
    event_callback: ValidationEventCallback | None,
) -> BackendRuntimeCommandResult:
    log_path = _step_log_path(live_logs_root, step_name)
    _emit_step_event(
        event_callback,
        step_name=step_name,
        phase_kind="start",
        command=command_preview,
        cwd=cwd,
        log_path=log_path,
        status="running",
    )
    result = command_factory(log_path)
    _emit_step_event(
        event_callback,
        step_name=step_name,
        phase_kind="finish",
        command=result.command,
        cwd=Path(result.cwd) if result.cwd else None,
        log_path=Path(result.log_path) if result.log_path else log_path,
        status="skipped" if result.skipped else ("completed" if result.passed else "failed"),
        duration_ms=result.duration_ms,
        skipped_reason=result.skipped_reason,
    )
    return result


def _emit_step_event(
    event_callback: ValidationEventCallback | None,
    *,
    step_name: str,
    phase_kind: str,
    command: list[str],
    cwd: Path | None,
    log_path: Path | None,
    status: str,
    duration_ms: int | None = None,
    skipped_reason: str | None = None,
    elapsed_ms: int | None = None,
) -> None:
    if event_callback is None:
        return
    details: dict[str, object] = {
        "step_name": step_name,
        "command": list(command),
        "cwd": str(cwd) if cwd is not None else None,
        "log_path": str(log_path) if log_path is not None else None,
        "status": status,
    }
    if duration_ms is not None:
        details["duration_ms"] = duration_ms
    if skipped_reason:
        details["skipped_reason"] = skipped_reason
    if elapsed_ms is not None:
        details["elapsed_ms"] = elapsed_ms
    summary_suffix = {
        "start": "started",
        "finish": "completed" if status == "completed" else ("failed" if status == "failed" else "skipped"),
        "progress": "still running",
    }[phase_kind]
    event_callback(
        {
            "phase": f"prep_{step_name}_{phase_kind}",
            "event_type": {
                "start": "backend_runtime_prep_step_started",
                "finish": "backend_runtime_prep_step_completed",
                "progress": "backend_runtime_prep_progress",
            }[phase_kind],
            "summary": f"backend runtime prep {step_name} {summary_suffix}",
            "details": details,
            "failure_signature": None,
        }
    )


def _step_progress_emitter(
    event_callback: ValidationEventCallback | None,
    *,
    step_name: str,
    command: list[str],
    cwd: Path,
    log_path: Path | None,
) -> ValidationEventCallback | None:
    if event_callback is None:
        return None

    def _emit(payload: dict[str, Any]) -> None:
        _emit_step_event(
            event_callback,
            step_name=step_name,
            phase_kind="progress",
            command=command,
            cwd=cwd,
            log_path=log_path,
            status="running",
            elapsed_ms=int(payload.get("elapsed_ms") or 0),
        )

    return _emit


def _record_live_log_path(mapping: dict[str, str], step_name: str, log_path: str | None) -> None:
    if log_path:
        mapping[step_name] = log_path


def _step_log_path(live_logs_root: Path | None, step_name: str) -> Path | None:
    if live_logs_root is None:
        return None
    return live_logs_root / f"prep-{step_name.replace('_', '-')}.log"


def _build_seed_source(
    *,
    workspace: Path,
    reset_path: Path | None,
    seed_path: Path | None,
    python_executable: Path,
) -> dict[str, object]:
    source: dict[str, object] = {
        "workspace": str(workspace),
        "python_executable": str(python_executable),
    }
    if seed_path is not None:
        source["seed_path"] = str(seed_path)
        source["seed_command"] = [str(python_executable), str(seed_path)]
    if reset_path is not None:
        source["reset_path"] = str(reset_path)
        source["reset_command"] = [str(python_executable), str(reset_path)]
    return source


def _build_fixture_manifest(
    *,
    available: bool,
    seed_source: dict[str, object],
    reason: str | None,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "available": available,
        "auth": {},
        "orders": {},
        "seed_source": seed_source,
    }
    if reason:
        manifest["reason"] = reason
    return manifest


def _prep_failure_summary(step_name: str, result: BackendRuntimeCommandResult) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if text:
        first_line = text.splitlines()[0].strip()
        return f"{step_name} failed: {first_line}"
    if result.returncode not in (None, 0):
        return f"{step_name} nonzero exit"
    return f"{step_name} failed"


def _skipped_command_result(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    stdout: str,
    skipped_reason: str,
    log_path: Path | None,
) -> BackendRuntimeCommandResult:
    return BackendRuntimeCommandResult(
        name=name,
        command=list(command),
        cwd=str(cwd),
        returncode=0,
        stdout=stdout,
        stderr="",
        passed=True,
        skipped=True,
        skipped_reason=skipped_reason,
        log_path=str(log_path) if log_path is not None else None,
    )


def _run_command(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    heartbeat_interval_s: float = 5.0,
    progress_callback: ValidationEventCallback | None = None,
    stdin_text: str | None = None,
) -> BackendRuntimeCommandResult:
    resolved_log_path = log_path.resolve() if log_path is not None else None
    if resolved_log_path is not None:
        resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    start = time.monotonic()
    last_heartbeat = start
    log_lock = threading.Lock()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env or os.environ),
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if stdin_text is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()

    def _write_log(text: str) -> None:
        if resolved_log_path is None:
            return
        with log_lock:
            with resolved_log_path.open("a", encoding="utf-8") as handle:
                handle.write(text)

    def _drain(pipe, collector: list[str]) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                collector.append(line)
                _write_log(line)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(
        target=_drain,
        args=(process.stdout, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain,
        args=(process.stderr, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    while process.poll() is None:
        time.sleep(0.1)
        now = time.monotonic()
        if progress_callback is not None and now - last_heartbeat >= heartbeat_interval_s:
            progress_callback(
                {
                    "name": name,
                    "elapsed_ms": int((now - start) * 1000),
                    "log_path": str(resolved_log_path) if resolved_log_path is not None else None,
                }
            )
            last_heartbeat = now

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    duration_ms = int((time.monotonic() - start) * 1000)
    return BackendRuntimeCommandResult(
        name=name,
        command=list(command),
        cwd=str(cwd),
        returncode=process.returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        passed=process.returncode == 0,
        log_path=str(resolved_log_path) if resolved_log_path is not None else None,
        duration_ms=duration_ms,
    )


def _choose_backend_entrypoint(
    *,
    snapshot: AnalysisSnapshot,
    backend_root: Path,
    defaults: tuple[str, ...],
) -> str:
    candidates = list(snapshot.repo_profile.backend_entrypoints)
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate_path.parts and candidate_path.parts[0] == "backend":
            relative = Path(*candidate_path.parts[1:])
        else:
            relative = candidate_path
        if (backend_root / relative).exists():
            return relative.as_posix()
    for default_name in defaults:
        if (backend_root / default_name).exists():
            return default_name
    return defaults[0]


def _module_name_from_path(path: Path) -> str:
    suffixless = path.with_suffix("")
    return ".".join(part for part in suffixless.parts if part)


def _collect_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=1)
    return stdout or "", stderr or ""


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _default_related_files(framework: str) -> list[str]:
    if framework == "django":
        return ["backend/manage.py", "backend/requirements.txt", "backend/chat_auth.py"]
    return ["requirements.txt", "chat_auth.py"]
