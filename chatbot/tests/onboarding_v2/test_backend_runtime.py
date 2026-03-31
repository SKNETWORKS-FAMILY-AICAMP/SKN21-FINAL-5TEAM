import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot, BackendSeams, DomainIntegration, FrontendSeams, RepoProfile
from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    BackendWiringPlan,
    FrontendIntegrationPlan,
    IntegrationPlan,
)
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePrepResult
from chatbot.src.onboarding_v2.validation import backend_runtime as backend_runtime_module
from chatbot.src.onboarding_v2.validation.backend_runtime import build_backend_runtime_plan, prepare_backend_runtime


def _snapshot(
    *,
    backend_framework: str,
    backend_entrypoints: list[str] | None = None,
    source_root: str = "/tmp/demo",
) -> AnalysisSnapshot:
    return AnalysisSnapshot(
        repo_profile=RepoProfile(
            site="demo",
            source_root=source_root,
            backend_framework=backend_framework,
            frontend_framework="react",
            auth_style="session_cookie",
            backend_entrypoints=list(backend_entrypoints or []),
        ),
        backend_seams=BackendSeams(),
        frontend_seams=FrontendSeams(),
        domain_integration=DomainIntegration(),
    )


def _plan(*, strategy: str) -> IntegrationPlan:
    return IntegrationPlan(
        host_backend=BackendWiringPlan(
            strategy=strategy,
            route_target="backend/config/urls.py",
            import_target="backend/config/urls.py",
            login_endpoint="/api/users/login/",
            auth_handler_source="backend/users/views.py",
            site_id="demo",
        ),
        host_frontend=FrontendIntegrationPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="demo",
            adapter_package="src/adapters/generated/demo",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_DEMO_API_URL",
            auth_validation_endpoint="/api/users/me/",
            current_user_endpoint="/api/users/me/",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
        ),
    )


def test_build_backend_runtime_plan_for_django(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
        plan=_plan(strategy="django_project_urlconf_import_view"),
        prep_result=BackendRuntimePrepResult(framework="django", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.listen_port is not None
    assert runtime_plan.command == [
        "/tmp/python",
        "manage.py",
        "runserver",
        f"127.0.0.1:{runtime_plan.listen_port}",
    ]
    assert runtime_plan.readiness_url == f"http://127.0.0.1:{runtime_plan.listen_port}/api/chat/auth-token"


def test_build_backend_runtime_plan_for_flask(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "app.py").write_text("app = object()\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="flask", backend_entrypoints=["backend/app.py"]),
        plan=_plan(strategy="flask_app_register_blueprint"),
        prep_result=BackendRuntimePrepResult(framework="flask", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.listen_port is not None
    assert runtime_plan.command[0] == "/tmp/python"
    assert Path(runtime_plan.command[1]).exists()
    assert runtime_plan.command[1].endswith("flask_validation_launcher.py")
    assert runtime_plan.launcher_mode == "flask_validation_launcher"
    assert runtime_plan.readiness_url == f"http://127.0.0.1:{runtime_plan.listen_port}/api/chat/auth-token"


def test_build_backend_runtime_plan_for_flask_does_not_reuse_detected_app_run_port(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "app.py").write_text(
        """
from flask import Flask

app = Flask(__name__)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="flask", backend_entrypoints=["backend/app.py"]),
        plan=_plan(strategy="flask_app_register_blueprint"),
        prep_result=BackendRuntimePrepResult(framework="flask", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.listen_port is not None
    assert runtime_plan.listen_port != 5000
    assert runtime_plan.readiness_url == f"http://127.0.0.1:{runtime_plan.listen_port}/api/chat/auth-token"
    launcher_text = Path(runtime_plan.command[1]).read_text(encoding="utf-8")
    assert "app.run(host='127.0.0.1', port=" in launcher_text or 'app.run(host="127.0.0.1", port=' in launcher_text


def test_build_backend_runtime_plan_for_flask_launcher_records_db_init_bypass_metadata(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "app.py").write_text(
        """
import os
from flask import Flask

app = Flask(__name__)

def init_db_with_retry():
    return None

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="flask", backend_entrypoints=["backend/app.py"]),
        plan=_plan(strategy="flask_app_register_blueprint"),
        prep_result=BackendRuntimePrepResult(framework="flask", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.launcher_mode == "flask_validation_launcher"
    assert runtime_plan.launcher_metadata_path is not None
    launcher_text = Path(runtime_plan.command[1]).read_text(encoding="utf-8")
    assert "ONBOARDING_VALIDATION" in launcher_text
    assert "ONBOARDING_VALIDATION_SKIP_DB_INIT" in launcher_text
    assert "init_db_with_retry" in launcher_text
    assert "startup_hooks_skipped" in launcher_text


def test_build_backend_runtime_plan_for_fastapi(tmp_path: Path):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "main.py").write_text("app = object()\n", encoding="utf-8")

    runtime_plan = build_backend_runtime_plan(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="fastapi", backend_entrypoints=["backend/main.py"]),
        plan=_plan(strategy="fastapi_include_router"),
        prep_result=BackendRuntimePrepResult(framework="fastapi", passed=True, python_executable="/tmp/python"),
    )

    assert runtime_plan.listen_port is not None
    assert runtime_plan.command == [
        "/tmp/python",
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(runtime_plan.listen_port),
    ]
    assert runtime_plan.readiness_url == f"http://127.0.0.1:{runtime_plan.listen_port}/api/chat/auth-token"


def test_prepare_backend_runtime_discovers_reset_and_seed_scripts(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    seed_root = backend_root / "seed"
    seed_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (seed_root / "reset.py").write_text("print('reset')\n", encoding="utf-8")
    (seed_root / "seed.py").write_text("print('seed')\n", encoding="utf-8")

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _ok_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert prep.reset is not None
    assert prep.seed is not None
    assert prep.reset.command[-1].endswith("backend/seed/reset.py")
    assert prep.seed.command[-1].endswith("backend/seed/seed.py")
    assert prep.reset_source_path.endswith("backend/seed/reset.py")
    assert prep.seed_source_path.endswith("backend/seed/seed.py")
    assert prep.fixture_manifest["seed_source"]["seed_path"].endswith("backend/seed/seed.py")
    assert prep.fixture_manifest["seed_source"]["reset_path"].endswith("backend/seed/reset.py")


def test_prepare_backend_runtime_keeps_fixture_manifest_metadata_when_seed_missing(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert prep.seed is not None
    assert prep.seed.skipped is True
    assert prep.fixture_manifest["available"] is False
    assert prep.fixture_manifest["reason"] == "fixture_unavailable"


def test_run_command_writes_live_log_and_emits_progress(tmp_path: Path):
    log_path = tmp_path / "live-logs" / "prep-reset.log"
    progress_events: list[dict[str, object]] = []
    command = [
        sys.executable,
        "-c",
        (
            "import sys,time; "
            "print('reset-start', flush=True); "
            "time.sleep(0.2); "
            "print('reset-stderr', file=sys.stderr, flush=True); "
            "time.sleep(0.2)"
        ),
    ]

    result = backend_runtime_module._run_command(
        name="reset",
        command=command,
        cwd=tmp_path,
        log_path=log_path,
        heartbeat_interval_s=0.1,
        progress_callback=lambda payload: progress_events.append(payload),
    )

    assert result.passed is True
    assert result.log_path == str(log_path)
    assert "reset-start" in result.stdout
    assert "reset-stderr" in result.stderr
    assert log_path.read_text(encoding="utf-8")
    assert progress_events
    assert all(event["log_path"] == str(log_path) for event in progress_events)


def test_run_command_uses_devnull_stdin_for_non_interactive_scripts(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "live-logs" / "prep-reset.log"
    captured: dict[str, object] = {}

    class _FakePipe:
        def readline(self):
            return ""

        def close(self):
            return None

    class _FakeProcess:
        def __init__(self):
            self.stdout = _FakePipe()
            self.stderr = _FakePipe()
            self.returncode = 0

        def poll(self):
            return 0

    def _fake_popen(command, **kwargs):
        captured["command"] = command
        captured["stdin"] = kwargs.get("stdin")
        return _FakeProcess()

    monkeypatch.setattr(backend_runtime_module.subprocess, "Popen", _fake_popen)

    result = backend_runtime_module._run_command(
        name="reset",
        command=[sys.executable, "-c", "input('continue? ')"],
        cwd=tmp_path,
        log_path=log_path,
        heartbeat_interval_s=0.1,
    )

    assert result.passed is True
    assert captured["stdin"] is backend_runtime_module.subprocess.DEVNULL


def test_prepare_backend_runtime_runs_interactive_reset_script_non_interactively(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (scripts_root / "reset_db.py").write_text(
        (
            "confirm = input('continue? ')\n"
            "if confirm.lower() != 'y':\n"
            "    raise SystemExit(1)\n"
            "print('reset ok')\n"
        ),
        encoding="utf-8",
    )
    (scripts_root / "seed.py").write_text("print('seed ok')\n", encoding="utf-8")

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_venv_python", lambda _: Path(sys.executable))
    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert prep.reset is not None
    assert prep.reset.passed is True
    assert "reset ok" in prep.reset.stdout
    assert prep.seed is not None
    assert prep.seed.passed is True


def test_prepare_backend_runtime_loads_workspace_dotenv_into_prep_script_env_without_overriding_process_env(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (workspace / ".env").write_text(
        "ORACLE_HOST=dotenv-host\nORACLE_SERVICE_NAME=freepdb1\nONLY_IN_DOTENV=1\n",
        encoding="utf-8",
    )
    (scripts_root / "reset_db.py").write_text("print('reset ok')\n", encoding="utf-8")
    (scripts_root / "seed.py").write_text("print('seed ok')\n", encoding="utf-8")
    monkeypatch.setenv("ORACLE_HOST", "process-host")

    captured_envs: dict[str, dict[str, str]] = {}

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, env=None, **kwargs):
        del kwargs
        if name in {"reset", "seed"}:
            captured_envs[name] = dict(env or {})
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _ok_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert captured_envs["reset"]["ORACLE_HOST"] == "process-host"
    assert captured_envs["reset"]["ORACLE_SERVICE_NAME"] == "freepdb1"
    assert captured_envs["seed"]["ONLY_IN_DOTENV"] == "1"
    assert prep.env_source["loaded_workspace_dotenv"] is True
    assert prep.env_source["workspace_dotenv_path"].endswith("/workspace/.env")


def test_prepare_backend_runtime_loads_source_root_dotenv_when_workspace_lacks_dotenv(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    source_root = tmp_path / "source"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    source_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (source_root / ".env").write_text(
        "ORACLE_HOST=source-host\nORACLE_SERVICE_NAME=sourcepdb\nONLY_IN_SOURCE=1\n",
        encoding="utf-8",
    )
    (scripts_root / "reset_db.py").write_text("print('reset ok')\n", encoding="utf-8")
    (scripts_root / "seed.py").write_text("print('seed ok')\n", encoding="utf-8")
    monkeypatch.delenv("ORACLE_HOST", raising=False)

    captured_envs: dict[str, dict[str, str]] = {}

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, env=None, **kwargs):
        del kwargs
        if name in {"reset", "seed"}:
            captured_envs[name] = dict(env or {})
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _ok_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django", source_root=str(source_root)),
    )

    assert prep.passed is True
    assert captured_envs["reset"]["ORACLE_HOST"] == "source-host"
    assert captured_envs["reset"]["ORACLE_SERVICE_NAME"] == "sourcepdb"
    assert captured_envs["seed"]["ONLY_IN_SOURCE"] == "1"
    assert prep.env_source["loaded_source_dotenv"] is True
    assert prep.env_source["source_dotenv_path"].endswith("/source/.env")


def test_prepare_backend_runtime_classifies_oracle_reset_failure_as_host_contract(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (scripts_root / "reset_db.py").write_text("print('reset')\n", encoding="utf-8")
    (scripts_root / "seed.py").write_text("print('seed')\n", encoding="utf-8")
    (workspace / ".env").write_text(
        "ORACLE_HOST=DESKTOP-IMG07LN\nORACLE_PORT=1521\nORACLE_SERVICE_NAME=xe\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ORACLE_USER", raising=False)
    monkeypatch.delenv("ORACLE_PASSWORD", raising=False)

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    def _run_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        if name != "reset":
            return _ok_command(name=name, command=command, cwd=cwd, log_path=log_path, **kwargs)
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=1,
            stdout="socket.gaierror: [Errno 8] nodename nor servname provided, or not known",
            stderr="oracledb.exceptions.OperationalError: DPY-6005: cannot connect to database",
            passed=False,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _run_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is False
    assert prep.failure_origin == "host_contract"
    assert prep.failure_code == "backend_runtime_prep_external_dependency_unavailable"
    assert prep.dependency_kind == "oracle"
    assert prep.required_env_keys == [
        "ORACLE_USER",
        "ORACLE_PASSWORD",
        "ORACLE_HOST",
        "ORACLE_PORT",
        "ORACLE_SERVICE_NAME",
    ]
    assert prep.dependency_diagnostics["missing_env_keys"] == [
        "ORACLE_USER",
        "ORACLE_PASSWORD",
    ]
    assert prep.fixture_manifest["failure_origin"] == "host_contract"
    assert prep.fixture_manifest["failure_code"] == "backend_runtime_prep_external_dependency_unavailable"


def test_prepare_backend_runtime_defers_oracle_reset_and_seed_until_runtime_probe(
    tmp_path: Path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (scripts_root / "reset_db.py").write_text("print('reset')\n", encoding="utf-8")
    (scripts_root / "seed.py").write_text("print('seed')\n", encoding="utf-8")
    (workspace / ".env").write_text(
        (
            "ORACLE_USER=oracle-user\n"
            "ORACLE_PASSWORD=oracle-password\n"
            "ORACLE_HOST=oracle-host\n"
            "ORACLE_PORT=1521\n"
            "ORACLE_SERVICE_NAME=freepdb1\n"
        ),
        encoding="utf-8",
    )

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    def _run_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        raise AssertionError(f"{name} should have been deferred, but ran {command!r}")

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _run_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert prep.reset is not None
    assert prep.reset.skipped is True
    assert prep.seed is not None
    assert prep.seed.skipped is True
    assert prep.fixture_manifest["available"] is False
    assert prep.fixture_manifest["reason"] == "runtime_fixture_discovery_pending"
    assert prep.fixture_manifest["deferred_seed_strategy"] == "runtime_order_probe"
    assert prep.fixture_manifest["dependency_kind"] == "oracle"


def test_prepare_backend_runtime_uses_five_second_default_heartbeats(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    scripts_root = workspace / "scripts"
    backend_root.mkdir(parents=True)
    scripts_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (scripts_root / "reset_db.py").write_text("print('reset ok')\n", encoding="utf-8")
    (scripts_root / "seed.py").write_text("print('seed ok')\n", encoding="utf-8")
    observed: list[float] = []

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        observed.append(float(kwargs["heartbeat_interval_s"]))
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(
        backend_runtime_module,
        "_create_venv",
        lambda *args, **kwargs: _ok_command(
            name="create_venv",
            command=["python", "-m", "venv"],
            cwd=tmp_path,
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        backend_runtime_module,
        "_install_backend_requirements",
        lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root, **kwargs),
    )
    monkeypatch.setattr(
        backend_runtime_module,
        "_run_django_migrate",
        lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root, **kwargs),
    )
    monkeypatch.setattr(
        backend_runtime_module,
        "_run_optional_script",
        lambda *,
        name,
        script_path,
        framework,
        backend_root,
        python_executable,
        env,
        missing_stdout,
        log_path=None,
        **kwargs: _ok_command(
            name=name,
            command=[str(python_executable), str(script_path)] if script_path is not None else [],
            cwd=backend_root,
            log_path=log_path,
            **kwargs,
        ),
    )

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
    )

    assert prep.passed is True
    assert observed
    assert all(interval == 5.0 for interval in observed)


def test_create_venv_treats_file_exists_race_as_reused_venv(tmp_path: Path, monkeypatch):
    venv_path = tmp_path / "venv"
    python_path = venv_path / "bin" / "python"

    def _failed_run_command(**kwargs):
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")
        return backend_runtime_module.BackendRuntimeCommandResult(
            name="create_venv",
            command=list(kwargs["command"]),
            cwd=str(kwargs["cwd"]),
            returncode=1,
            stdout="",
            stderr="Error: [Errno 17] File exists: 'site-packages'",
            passed=False,
            log_path=str(kwargs.get("log_path")) if kwargs.get("log_path") is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_run_command", _failed_run_command)

    result = backend_runtime_module._create_venv(
        sys.executable,
        venv_path,
    )

    assert result.passed is True
    assert result.skipped is True
    assert result.skipped_reason == "existing venv reused"


def test_prepare_backend_runtime_emits_step_events_and_records_skips(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    live_logs_root = tmp_path / "generated" / "artifacts" / "05-validation" / "live-logs"
    observed_events: list[dict[str, object]] = []

    def _record_event(payload: dict[str, object]) -> None:
        observed_events.append(payload)

    def _ok_command(*, name: str, command: list[str], cwd: Path, log_path: Path | None = None, **kwargs):
        del kwargs
        return backend_runtime_module.BackendRuntimeCommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            stdout=f"{name} ok",
            stderr="",
            passed=True,
            log_path=str(log_path) if log_path is not None else None,
        )

    monkeypatch.setattr(backend_runtime_module, "_create_venv", lambda *args, **kwargs: _ok_command(name="create_venv", command=["python", "-m", "venv"], cwd=tmp_path, log_path=kwargs.get("log_path")))
    monkeypatch.setattr(backend_runtime_module, "_install_backend_requirements", lambda **kwargs: _ok_command(name="install", command=["pip", "install"], cwd=backend_root, log_path=kwargs.get("log_path")))
    monkeypatch.setattr(backend_runtime_module, "_run_django_migrate", lambda **kwargs: _ok_command(name="migrate", command=["manage.py", "migrate"], cwd=backend_root, log_path=kwargs.get("log_path")))
    monkeypatch.setattr(backend_runtime_module, "_run_command", _ok_command)

    prep = prepare_backend_runtime(
        workspace=workspace,
        snapshot=_snapshot(backend_framework="django"),
        live_logs_root=live_logs_root,
        event_callback=_record_event,
    )

    assert prep.passed is True
    phases = [str(event["phase"]) for event in observed_events]
    assert phases[:6] == [
        "prep_venv_start",
        "prep_venv_finish",
        "prep_install_start",
        "prep_install_finish",
        "prep_migrate_start",
        "prep_migrate_finish",
    ]
    assert "prep_reset_finish" in phases
    assert "prep_seed_finish" in phases
    assert "prep_fixture_manifest_finish" in phases
    reset_finish = next(event for event in observed_events if event["phase"] == "prep_reset_finish")
    seed_finish = next(event for event in observed_events if event["phase"] == "prep_seed_finish")
    assert reset_finish["details"]["status"] == "skipped"
    assert seed_finish["details"]["status"] == "skipped"
    assert "skipped_reason" in reset_finish["details"]
    assert "skipped_reason" in seed_finish["details"]
    assert prep.create_venv is not None and prep.create_venv.log_path is not None
    assert prep.install is not None and prep.install.log_path is not None
    assert prep.migrate is not None and prep.migrate.log_path is not None
