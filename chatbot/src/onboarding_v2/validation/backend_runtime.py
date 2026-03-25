from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from chatbot.src.onboarding.runtime_completion_runner import _probe_http_ready, _terminate_process
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimeCommandResult,
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
)


def prepare_backend_runtime(
    *,
    workspace: str | Path,
    snapshot: AnalysisSnapshot,
) -> BackendRuntimePrepResult:
    workspace = Path(workspace).resolve()
    backend_root = _resolve_backend_root(workspace)
    framework = snapshot.repo_profile.backend_framework
    runtime_root = _resolve_validation_support_root(workspace)
    venv_path = runtime_root / "venv"
    python_executable = _venv_python(venv_path)
    runtime_root.mkdir(parents=True, exist_ok=True)

    create_venv = _create_venv(sys.executable, venv_path)
    if not create_venv.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=create_venv.stderr or create_venv.stdout or "failed to create backend runtime venv",
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            related_files=_default_related_files(framework),
        )

    install = _install_backend_requirements(backend_root=backend_root, python_executable=python_executable)
    if not install.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=install.stderr or install.stdout or "dependency install failed",
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            related_files=_default_related_files(framework),
        )

    migrate = _run_django_migrate(
        framework=framework,
        backend_root=backend_root,
        python_executable=python_executable,
    )
    if not migrate.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=migrate.stderr or migrate.stdout or "backend migrate failed",
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            related_files=_default_related_files(framework),
        )

    seed = _run_optional_seed(
        framework=framework,
        backend_root=backend_root,
        python_executable=python_executable,
    )
    if not seed.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=seed.stderr or seed.stdout or "backend seed failed",
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            seed=seed,
            related_files=_default_related_files(framework),
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
        seed=seed,
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
    readiness_url = "http://127.0.0.1:8000" + plan.backend_wiring.chat_auth_contract_path
    environment = {"PYTHONUNBUFFERED": "1"}

    if framework == "django":
        command = [python_executable, "manage.py", "runserver", "127.0.0.1:8000"]
    elif framework == "flask":
        entrypoint = _choose_backend_entrypoint(snapshot=snapshot, backend_root=backend_root, defaults=("app.py", "run.py"))
        command = [python_executable, entrypoint]
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
            "8000",
        ]
    else:
        command = [python_executable, "manage.py", "runserver", "127.0.0.1:8000"]

    return BackendRuntimePlan(
        framework=framework,
        backend_root=str(backend_root),
        command=command,
        readiness_url=readiness_url,
        environment=environment,
        python_executable=str(python_executable),
    )


def launch_backend_runtime(plan: BackendRuntimePlan) -> BackendRuntimeState:
    environment = os.environ.copy()
    environment.update(plan.environment)
    process = subprocess.Popen(
        plan.command,
        cwd=plan.backend_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    readiness = _probe_http_ready(plan.readiness_url)
    if readiness.get("passed"):
        return BackendRuntimeState(
            framework=plan.framework,
            passed=True,
            pid=process.pid,
            command=list(plan.command),
            readiness_url=plan.readiness_url,
            readiness=readiness,
            related_files=_default_related_files(plan.framework),
            process_handle=process,
        )

    stdout, stderr = _collect_process_output(process)
    _terminate_process(process)
    return BackendRuntimeState(
        framework=plan.framework,
        passed=False,
        pid=process.pid,
        command=list(plan.command),
        readiness_url=plan.readiness_url,
        readiness=readiness,
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


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _create_venv(python_executable: str, venv_path: Path) -> BackendRuntimeCommandResult:
    if _venv_python(venv_path).exists():
        return BackendRuntimeCommandResult(
            name="create_venv",
            command=[python_executable, "-m", "venv", str(venv_path)],
            cwd=str(venv_path.parent),
            returncode=0,
            stdout="existing venv reused",
            stderr="",
            passed=True,
            skipped=True,
        )
    return _run_command(
        name="create_venv",
        command=[python_executable, "-m", "venv", str(venv_path)],
        cwd=venv_path.parent,
    )


def _install_backend_requirements(*, backend_root: Path, python_executable: Path) -> BackendRuntimeCommandResult:
    requirements_path = backend_root / "requirements.txt"
    if not requirements_path.exists():
        return BackendRuntimeCommandResult(
            name="install",
            command=[],
            cwd=str(backend_root),
            returncode=0,
            stdout="requirements.txt not found; skipped install",
            stderr="",
            passed=True,
            skipped=True,
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
    )


def _run_django_migrate(*, framework: str, backend_root: Path, python_executable: Path) -> BackendRuntimeCommandResult:
    if framework != "django" or not (backend_root / "manage.py").exists():
        return BackendRuntimeCommandResult(
            name="migrate",
            command=[],
            cwd=str(backend_root),
            returncode=0,
            stdout="migrate skipped",
            stderr="",
            passed=True,
            skipped=True,
        )
    return _run_command(
        name="migrate",
        command=[str(python_executable), "manage.py", "migrate", "--noinput"],
        cwd=backend_root,
    )


def _run_optional_seed(*, framework: str, backend_root: Path, python_executable: Path) -> BackendRuntimeCommandResult:
    if framework != "django":
        return BackendRuntimeCommandResult(
            name="seed",
            command=[],
            cwd=str(backend_root),
            returncode=0,
            stdout="seed skipped",
            stderr="",
            passed=True,
            skipped=True,
        )
    seed_path = backend_root / "seed" / "seed.py"
    if not seed_path.exists():
        return BackendRuntimeCommandResult(
            name="seed",
            command=[],
            cwd=str(backend_root),
            returncode=0,
            stdout="seed.py not found; skipped seed",
            stderr="",
            passed=True,
            skipped=True,
        )
    return _run_command(
        name="seed",
        command=[str(python_executable), str(seed_path)],
        cwd=backend_root,
    )


def _run_command(*, name: str, command: list[str], cwd: Path) -> BackendRuntimeCommandResult:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return BackendRuntimeCommandResult(
        name=name,
        command=list(command),
        cwd=str(cwd),
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        passed=result.returncode == 0,
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


def _default_related_files(framework: str) -> list[str]:
    if framework == "django":
        return ["backend/manage.py", "backend/requirements.txt", "backend/chat_auth.py"]
    return ["requirements.txt", "chat_auth.py"]
