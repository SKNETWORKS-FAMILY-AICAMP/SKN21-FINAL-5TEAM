from __future__ import annotations

import ast
import json
import os
import socket
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
            fixture_manifest=_build_fixture_manifest(
                available=False,
                seed_source={},
                reason=migrate.stderr or migrate.stdout or "backend migrate failed",
            ),
            related_files=_default_related_files(framework),
        )

    reset_path = _discover_reset_script(workspace=workspace, backend_root=backend_root)
    seed_path = _discover_seed_script(workspace=workspace, backend_root=backend_root)
    reset = _run_optional_script(
        name="reset",
        script_path=reset_path,
        framework=framework,
        backend_root=backend_root,
        python_executable=python_executable,
        missing_stdout="reset script not found; skipped reset",
    )
    if not reset.passed:
        return BackendRuntimePrepResult(
            framework=framework,
            passed=False,
            failure_summary=reset.stderr or reset.stdout or "backend reset failed",
            backend_root=str(backend_root),
            venv_path=str(venv_path),
            python_executable=str(python_executable),
            create_venv=create_venv,
            install=install,
            migrate=migrate,
            reset=reset,
            seed_source_path=str(seed_path) if seed_path is not None else None,
            reset_source_path=str(reset_path) if reset_path is not None else None,
            fixture_manifest=_build_fixture_manifest(
                available=False,
                seed_source=_build_seed_source(
                    workspace=workspace,
                    reset_path=reset_path,
                    seed_path=seed_path,
                    python_executable=python_executable,
                ),
                reason=reset.stderr or reset.stdout or "backend reset failed",
            ),
            related_files=_default_related_files(framework),
        )

    seed = _run_optional_script(
        name="seed",
        script_path=seed_path,
        framework=framework,
        backend_root=backend_root,
        python_executable=python_executable,
        missing_stdout="seed script not found; skipped seed",
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
            reset=reset,
            seed=seed,
            seed_source_path=str(seed_path) if seed_path is not None else None,
            reset_source_path=str(reset_path) if reset_path is not None else None,
            fixture_manifest=_build_fixture_manifest(
                available=False,
                seed_source=_build_seed_source(
                    workspace=workspace,
                    reset_path=reset_path,
                    seed_path=seed_path,
                    python_executable=python_executable,
                ),
                reason=seed.stderr or seed.stdout or "backend seed failed",
            ),
            related_files=_default_related_files(framework),
        )

    fixture_manifest = _build_fixture_manifest(
        available=seed_path is not None and not seed.skipped,
        seed_source=_build_seed_source(
            workspace=workspace,
            reset_path=reset_path,
            seed_path=seed_path,
            python_executable=python_executable,
        ),
        reason=None if seed_path is not None and not seed.skipped else "fixture_unavailable",
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
        listen_port=plan.listen_port,
        launcher_mode=str(launcher_metadata.get("launcher_mode") or plan.launcher_mode or ""),
        startup_hooks_skipped=list(launcher_metadata.get("startup_hooks_skipped") or []),
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


def _run_optional_script(
    *,
    name: str,
    script_path: Path | None,
    framework: str,
    backend_root: Path,
    python_executable: Path,
    missing_stdout: str,
) -> BackendRuntimeCommandResult:
    del framework
    if script_path is None:
        return BackendRuntimeCommandResult(
            name=name,
            command=[],
            cwd=str(backend_root),
            returncode=0,
            stdout=missing_stdout,
            stderr="",
            passed=True,
            skipped=True,
        )
    return _run_command(
        name=name,
        command=[str(python_executable), str(script_path)],
        cwd=backend_root,
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
