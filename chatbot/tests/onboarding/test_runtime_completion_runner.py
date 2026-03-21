import json
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding import runtime_completion_runner as runtime_completion_runner_module
from chatbot.src.onboarding.runtime_completion_runner import run_runtime_completion


def test_runtime_completion_runner_contract_writes_failure_artifacts(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-013"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-013" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "dev": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_runtime_completion(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        site="food",
        run_id="food-run-013",
        server_probe_runner=lambda context: {
            "attempt_count": 1,
            "passed": False,
            "failure_reason": "runtime_server_probes_not_implemented",
            "backend": {
                "plan": context["backend_plan"],
                "passed": False,
                "status": "not_started",
            },
            "frontend": {
                "plan": context["frontend_plan"],
                "passed": False,
                "status": "not_started",
            },
        },
    )

    assert result["passed"] is False
    assert result["failure_reason"] == "runtime_server_probes_not_implemented"
    assert result["attempt_count"] == 1
    assert result["backend_probe"]["plan"]["framework"] == "django"
    assert result["backend_probe"]["plan"]["command"] == [
        sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8000",
        "--noreload",
    ]
    assert result["backend_probe"]["plan"]["readiness_method"] == "POST"
    assert result["backend_probe"]["plan"]["readiness_expected_statuses"] == [200, 401]
    assert result["frontend_probe"]["plan"]["package_manager"] == "npm"
    assert result["frontend_probe"]["plan"]["command"] == ["npm", "run", "dev"]
    assert result["frontend_probe"]["plan"]["environment"] == {
        "PORT": "3000",
        "BROWSER": "none",
        "REACT_APP_CHATBOT_API_BASE": "http://127.0.0.1:8100",
    }

    completion_report = run_root / "reports" / "runtime-completion.json"
    server_probe_report = run_root / "reports" / "runtime-server-probes.json"
    completion_payload = json.loads(completion_report.read_text(encoding="utf-8"))
    probe_payload = json.loads(server_probe_report.read_text(encoding="utf-8"))

    assert completion_payload["failure_reason"] == "runtime_server_probes_not_implemented"
    assert completion_payload["attempt_count"] == 1
    assert probe_payload["backend"]["plan"]["framework"] == "django"
    assert probe_payload["frontend"]["plan"]["command"] == ["npm", "run", "dev"]


def test_build_backend_probe_plan_skips_non_runnable_flask_module(tmp_path: Path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )

    plan = runtime_completion_runner_module._build_backend_probe_plan(tmp_path)

    assert plan["framework"] == "flask"
    assert plan["command"] is None
    assert plan["startup_command"] is None


def test_build_backend_probe_plan_prefers_bootstrapped_python_when_available(tmp_path: Path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    bootstrapped_python = backend_root / ".venv" / "bin" / "python"
    bootstrapped_python.parent.mkdir(parents=True)
    bootstrapped_python.write_text("#!/bin/sh\n", encoding="utf-8")

    plan = runtime_completion_runner_module._build_backend_probe_plan(tmp_path)

    assert plan["command"] == [
        str(bootstrapped_python),
        "manage.py",
        "runserver",
        "127.0.0.1:8000",
        "--noreload",
    ]


def test_build_backend_probe_plan_resolves_relative_bootstrapped_python_to_absolute_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = Path("workspace")
    backend_root = workspace / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    bootstrapped_python = backend_root / ".venv" / "bin" / "python"
    bootstrapped_python.parent.mkdir(parents=True)
    bootstrapped_python.write_text("#!/bin/sh\n", encoding="utf-8")

    plan = runtime_completion_runner_module._build_backend_probe_plan(workspace)

    assert Path(plan["command"][0]).is_absolute()
    assert Path(plan["command"][0]) == bootstrapped_python.resolve()
    assert plan["readiness_method"] == "POST"
    assert plan["readiness_expected_statuses"] == [200, 401]
    assert plan["readiness_timeout_seconds"] == 3
    assert plan["readiness_attempts"] == 30
    assert plan["readiness_delay_seconds"] == 0.5


def test_build_backend_probe_plan_preserves_virtualenv_entrypoint_symlink(tmp_path: Path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "manage.py").write_text("print('django')\n", encoding="utf-8")
    bootstrapped_python = backend_root / ".venv" / "bin" / "python"
    target_python = backend_root / ".venv" / "bin" / "python3.13"
    target_python.parent.mkdir(parents=True)
    target_python.write_text("#!/bin/sh\n", encoding="utf-8")
    bootstrapped_python.symlink_to(target_python.name)

    plan = runtime_completion_runner_module._build_backend_probe_plan(tmp_path)

    assert plan["command"][0] == str(bootstrapped_python.absolute())


def test_build_frontend_probe_plan_sets_localhost_runtime_environment(tmp_path: Path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir(parents=True)
    (frontend_root / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "dev": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    plan = runtime_completion_runner_module._build_frontend_probe_plan(tmp_path)

    assert plan["command"] == ["npm", "run", "dev"]
    assert plan["environment"] == {
        "PORT": "3000",
        "BROWSER": "none",
        "REACT_APP_CHATBOT_API_BASE": "http://127.0.0.1:8100",
    }


def test_build_chatbot_probe_plan_launches_local_shared_server_for_food(tmp_path: Path):
    plan = runtime_completion_runner_module._build_chatbot_probe_plan(tmp_path, site="food")

    assert plan["working_directory"] == str(Path(__file__).resolve().parents[3])
    assert plan["command"] == [
        sys.executable,
        "-m",
        "uvicorn",
        "chatbot.server_fastapi:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
    ]
    assert plan["environment"]["FOOD_API_URL"] == "http://127.0.0.1:8000"
    assert plan["readiness_url"] == "http://127.0.0.1:8100/health"


def test_probe_http_ready_accepts_expected_http_error_status(monkeypatch):
    def _raise_http_error(request, timeout=0):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8000/api/chat/auth-token",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(runtime_completion_runner_module.urllib.request, "urlopen", _raise_http_error)

    readiness = runtime_completion_runner_module._probe_http_ready(
        "http://127.0.0.1:8000/api/chat/auth-token",
        method="POST",
        accepted_statuses={200, 401},
        attempts=1,
    )

    assert readiness["passed"] is True
    assert readiness["status_code"] == 401


def test_collect_process_output_reads_file_backed_logs_without_communicate():
    class _FileBackedProcess:
        def __init__(self) -> None:
            self.stdout = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.stdout.write("frontend boot ok\n")
            self.stderr.write("warning line\n")

        def communicate(self, timeout=None):
            raise AssertionError("communicate should not be used for file-backed logs")

    process = _FileBackedProcess()

    stdout, stderr = runtime_completion_runner_module._collect_process_output(process)

    assert stdout == "frontend boot ok\n"
    assert stderr == "warning line\n"


def test_terminate_process_uses_process_group_when_pid_exists(monkeypatch):
    events: list[tuple[str, int]] = []

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 43210
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            events.append(("terminate", self.pid))
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            events.append(("kill", self.pid))
            self.returncode = -9

    monkeypatch.setattr(
        runtime_completion_runner_module.os,
        "killpg",
        lambda pid, sig: events.append(("killpg", pid)),
    )

    process = _FakeProcess()
    runtime_completion_runner_module._terminate_process(process)

    assert events == [("killpg", 43210)]


def test_runtime_completion_runner_readiness_records_server_probe_outputs(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-014"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-014" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "start": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    class _FakeProcess:
        def __init__(self, pid: int, stdout: str, stderr: str = "") -> None:
            self.pid = pid
            self._stdout = stdout
            self._stderr = stderr
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return self._stdout, self._stderr

    launched: list[tuple[list[str], str]] = []
    fake_processes = iter(
        [
            _FakeProcess(4101, "backend boot ok\n"),
            _FakeProcess(4102, "chatbot boot ok\n"),
            _FakeProcess(4103, "frontend boot ok\n"),
        ]
    )

    def _fake_launch(command, cwd, env=None):
        launched.append((list(command), str(cwd)))
        return next(fake_processes)

    def _fake_probe(url, method="GET", accepted_statuses=None, timeout_seconds=0, attempts=0, delay_seconds=0.0):
        if "3000" in url:
            return {
                "passed": True,
                "url": url,
                "method": method,
                "status_code": 200,
                "attempts": 1,
                "error": None,
            }
        return {
            "passed": True,
            "url": url,
            "method": method,
            "status_code": 200,
            "attempts": 1,
            "error": None,
        }

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=_fake_launch,
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        side_effect=_fake_probe,
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._run_mount_probe",
        return_value={
            "passed": True,
            "failure_reason": None,
            "lightweight_probe": {
                "mount_file": "frontend/src/App.js",
                "widget_file": "frontend/src/chatbot/SharedChatbotWidget.jsx",
                "wiring_detected": True,
                "page_url": "http://127.0.0.1:3000",
            },
            "browser_probe": {
                "status": "authenticated",
                "selector": "[data-chatbot-status]",
                "value": "authenticated",
            },
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-014",
        )

    backend_port = launched[0][0][3].split(":")[-1]
    chatbot_port = launched[1][0][-1]
    assert result["passed"] is True
    assert result["failure_reason"] is None
    assert launched[0][0] == [sys.executable, "manage.py", "runserver", f"127.0.0.1:{backend_port}", "--noreload"]
    assert launched[1][0] == [
        sys.executable,
        "-m",
        "uvicorn",
        "chatbot.server_fastapi:app",
        "--host",
        "127.0.0.1",
        "--port",
        chatbot_port,
    ]
    assert launched[2][0] == ["npm", "run", "start"]
    assert result["backend_probe"]["status"] == "ready"
    assert result["backend_probe"]["stdout"] == "backend boot ok\n"
    assert result["chatbot_probe"]["status"] == "ready"
    assert result["chatbot_probe"]["stdout"] == "chatbot boot ok\n"
    assert result["frontend_probe"]["status"] == "ready"
    assert result["frontend_probe"]["stdout"] == "frontend boot ok\n"
    assert result["chatbot_probe"]["plan"]["environment"]["FOOD_API_URL"] == f"http://127.0.0.1:{backend_port}"
    assert result["frontend_probe"]["plan"]["environment"]["REACT_APP_CHATBOT_API_BASE"] == f"http://127.0.0.1:{chatbot_port}"

    probe_payload = json.loads((run_root / "reports" / "runtime-server-probes.json").read_text(encoding="utf-8"))
    assert probe_payload["passed"] is True
    assert probe_payload["backend"]["readiness"]["status_code"] == 200
    assert probe_payload["chatbot"]["stdout"] == "chatbot boot ok\n"
    assert probe_payload["frontend"]["stdout"] == "frontend boot ok\n"


def test_runtime_completion_runner_uses_isolated_ports_for_contract_probe(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-ports"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-ports" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "dev": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-ports",
                "site": "food",
                "analysis": {
                    "auth": {
                        "login_route": "/api/users/login/",
                        "login_fields": ["email", "password"],
                    }
                },
                "credentials": {
                    "email": "test1@example.com",
                    "password": "password123",
                },
            }
        ),
        encoding="utf-8",
    )

    class _FakeProcess:
        def __init__(self, pid: int, stdout: str) -> None:
            self.pid = pid
            self._stdout = stdout
            self._stderr = ""
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return self._stdout, self._stderr

    port_values = iter([19100, 19110, 19130])
    launched: list[list[str]] = []
    fake_processes = iter(
        [
            _FakeProcess(6101, "backend boot ok\n"),
            _FakeProcess(6102, "chatbot boot ok\n"),
            _FakeProcess(6103, "frontend boot ok\n"),
        ]
    )
    contract_calls: dict[str, str] = {}

    monkeypatch.setattr(runtime_completion_runner_module, "_reserve_loopback_port", lambda: next(port_values))

    def _fake_launch(command, cwd, env=None):
        launched.append(list(command))
        return next(fake_processes)

    def _fake_probe(url, method="GET", accepted_statuses=None, timeout_seconds=0, attempts=0, delay_seconds=0.0):
        return {
            "passed": True,
            "url": url,
            "method": method,
            "status_code": 200,
            "attempts": 1,
            "error": None,
        }

    def _fake_contract_probe(*, site, credentials=None, auth=None, http_request=None, backend_base_url=None, chatbot_base_url=None):
        contract_calls["backend_base_url"] = backend_base_url
        contract_calls["chatbot_base_url"] = chatbot_base_url
        return {
            "status": "passed",
            "passed": True,
            "failure_reason": None,
            "chat_auth": {"status": 200, "headers": {}, "body": "", "exports": {}},
            "chatbot_stream": {"status": 200, "headers": {}, "body": "data: ok", "request_body": {}},
        }

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=_fake_launch,
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        side_effect=_fake_probe,
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._run_authenticated_chat_contract_probe",
        side_effect=_fake_contract_probe,
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._run_mount_probe",
        return_value={
            "passed": True,
            "failure_reason": None,
            "lightweight_probe": {
                "mount_file": "frontend/src/App.js",
                "widget_file": "frontend/src/chatbot/SharedChatbotWidget.jsx",
                "wiring_detected": True,
                "page_url": "http://127.0.0.1:19130",
                "status_attribute_present": True,
            },
            "browser_probe": {
                "status": "authenticated",
                "selector": "[data-chatbot-status]",
                "value": "authenticated",
            },
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-ports",
        )

    assert result["passed"] is True
    assert launched[0][-2:] == ["127.0.0.1:19100", "--noreload"]
    assert launched[1][-2:] == ["--port", "19110"]
    assert launched[2] == ["npm", "run", "dev"]
    assert contract_calls["backend_base_url"] == "http://127.0.0.1:19100"
    assert contract_calls["chatbot_base_url"] == "http://127.0.0.1:19110"


def test_runtime_completion_runner_mount_probe_accepts_unsupported_browser_environment_when_widget_exposes_status_marker(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-015"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-015" / "workspace"

    (runtime_workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div data-chatbot-status=\"authenticated\">Chat</div>; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "export default function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )

    result = run_runtime_completion(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        site="food",
        run_id="food-run-015",
        server_probe_runner=lambda context: {
            "attempt_count": 1,
            "passed": True,
            "failure_reason": None,
            "backend": {"passed": True, "status": "ready", "plan": context["backend_plan"]},
            "chatbot": {"passed": True, "status": "ready", "plan": context["chatbot_plan"]},
            "frontend": {"passed": True, "status": "ready", "plan": context["frontend_plan"]},
        },
    )

    assert result["passed"] is True
    assert result["failure_reason"] is None
    assert result["mount_probe"]["lightweight_probe"]["wiring_detected"] is True
    assert result["mount_probe"]["browser_probe"]["status"] == "unsupported_environment"

    mount_probe_payload = json.loads((run_root / "reports" / "runtime-mount-probe.json").read_text(encoding="utf-8"))
    assert mount_probe_payload["failure_reason"] is None
    assert mount_probe_payload["lightweight_probe"]["mount_file"] == "frontend/src/App.js"


def test_runtime_completion_runner_mount_probe_still_fails_without_status_marker(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-016"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-016" / "workspace"

    (runtime_workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "export default function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )

    result = run_runtime_completion(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        site="food",
        run_id="food-run-016",
        server_probe_runner=lambda context: {
            "attempt_count": 1,
            "passed": True,
            "failure_reason": None,
            "backend": {"passed": True, "status": "ready", "plan": context["backend_plan"]},
            "chatbot": {"passed": True, "status": "ready", "plan": context["chatbot_plan"]},
            "frontend": {"passed": True, "status": "ready", "plan": context["frontend_plan"]},
        },
    )

    assert result["passed"] is False
    assert result["failure_reason"] == "mount_probe_environment_unsupported"
    assert result["mount_probe"]["lightweight_probe"]["status_attribute_present"] is False


def test_runtime_completion_runner_classifies_shared_widget_import_failure(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-016"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-016" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "start": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    class _BackendProcess:
        pid = 5101
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "backend ok\n", ""

    class _FrontendProcess:
        pid = 5102
        returncode = 1

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

        def communicate(self, timeout=None):
            return (
                "",
                "Module not found: Error: Can't resolve '@shared-chatbot/ChatbotWidget' in '/workspace/frontend/src/chatbot'\n",
            )

    class _ChatbotProcess:
        pid = 51015
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "chatbot ok\n", ""

    launched = iter([_BackendProcess(), _ChatbotProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd, env=None: next(launched),
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        return_value={
            "passed": True,
            "url": "http://127.0.0.1:8000/api/chat/auth-token",
            "status_code": 200,
            "attempts": 1,
            "error": None,
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-016",
        )

    assert result["passed"] is False
    assert result["failure_reason"] == "frontend_import_resolution_failed"
    assert result["frontend_probe"]["failure_reason"] == "frontend_import_resolution_failed"
    assert "Can't resolve '@shared-chatbot/ChatbotWidget'" in result["frontend_probe"]["stderr"]


def test_runtime_completion_runner_classifies_shared_widget_import_failure_with_module_not_found_wording(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-016b"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-016b" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "start": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    class _BackendProcess:
        pid = 5103
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "backend ok\n", ""

    class _FrontendProcess:
        pid = 5104
        returncode = 1

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

        def communicate(self, timeout=None):
            return (
                "",
                "Module not found: Can't resolve '@shared-chatbot/ChatbotWidget' in '/workspace/frontend/src/chatbot'\n",
            )

    class _ChatbotProcess:
        pid = 51045
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "chatbot ok\n", ""

    launched = iter([_BackendProcess(), _ChatbotProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd, env=None: next(launched),
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        return_value={
            "passed": True,
            "url": "http://127.0.0.1:8000/api/chat/auth-token",
            "status_code": 200,
            "attempts": 1,
            "error": None,
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-016b",
        )

    assert result["passed"] is False
    assert result["failure_reason"] == "frontend_import_resolution_failed"
    assert result["frontend_probe"]["failure_reason"] == "frontend_import_resolution_failed"


def test_runtime_completion_runner_classifies_backend_import_resolution_failure(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-017"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-017" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "start": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    class _BackendProcess:
        pid = 6101
        returncode = 1

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

        def communicate(self, timeout=None):
            return (
                "",
                "ModuleNotFoundError: No module named 'backend'\n",
            )

    class _FrontendProcess:
        pid = 6102
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    class _ChatbotProcess:
        pid = 61025
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "chatbot ok\n", ""

    launched = iter([_BackendProcess(), _ChatbotProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd, env=None: next(launched),
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        return_value={
            "passed": True,
            "url": "http://127.0.0.1:3000",
            "status_code": 200,
            "attempts": 1,
            "error": None,
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-017",
        )

    assert result["passed"] is False
    assert result["failure_reason"] == "backend_import_resolution_failed"
    assert result["backend_probe"]["failure_reason"] == "backend_import_resolution_failed"
    assert "No module named 'backend'" in result["backend_probe"]["stderr"]


def test_runtime_completion_runner_classifies_django_urlconf_import_failure(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-018"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-018" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "start": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    class _BackendProcess:
        pid = 6103
        returncode = 1

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            return None

        def communicate(self, timeout=None):
            return (
                "",
                "Traceback (most recent call last):\n"
                '  File "/workspace/backend/foodshop/urls.py", line 4, in <module>\n'
                "    from backend.chat_auth import chat_auth_token\n"
                "ModuleNotFoundError: No module named 'backend'\n",
            )

    class _FrontendProcess:
        pid = 6104
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    class _ChatbotProcess:
        pid = 61045
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "chatbot ok\n", ""

    launched = iter([_BackendProcess(), _ChatbotProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd, env=None: next(launched),
    ), patch(
        "chatbot.src.onboarding.runtime_completion_runner._probe_http_ready",
        return_value={
            "passed": True,
            "url": "http://127.0.0.1:3000",
            "status_code": 200,
            "attempts": 1,
            "error": None,
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-018",
        )

    assert result["passed"] is False
    assert result["failure_reason"] == "django_urlconf_import_failed"
    assert result["backend_probe"]["failure_reason"] == "django_urlconf_import_failed"
    assert "urls.py" in result["backend_probe"]["stderr"]
