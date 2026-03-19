import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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
        "python",
        "manage.py",
        "runserver",
        "127.0.0.1:8000",
    ]
    assert result["frontend_probe"]["plan"]["package_manager"] == "npm"
    assert result["frontend_probe"]["plan"]["command"] == ["npm", "run", "dev"]

    completion_report = run_root / "reports" / "runtime-completion.json"
    server_probe_report = run_root / "reports" / "runtime-server-probes.json"
    completion_payload = json.loads(completion_report.read_text(encoding="utf-8"))
    probe_payload = json.loads(server_probe_report.read_text(encoding="utf-8"))

    assert completion_payload["failure_reason"] == "runtime_server_probes_not_implemented"
    assert completion_payload["attempt_count"] == 1
    assert probe_payload["backend"]["plan"]["framework"] == "django"
    assert probe_payload["frontend"]["plan"]["command"] == ["npm", "run", "dev"]


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
            _FakeProcess(4102, "frontend boot ok\n"),
        ]
    )

    def _fake_launch(command, cwd):
        launched.append((list(command), str(cwd)))
        return next(fake_processes)

    def _fake_probe(url, timeout_seconds=0, attempts=0, delay_seconds=0.0):
        if "3000" in url:
            return {
                "passed": True,
                "url": url,
                "status_code": 200,
                "attempts": 1,
                "error": None,
            }
        return {
            "passed": True,
            "url": url,
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

    assert result["passed"] is True
    assert result["failure_reason"] is None
    assert launched[0][0] == ["python", "manage.py", "runserver", "127.0.0.1:8000"]
    assert launched[1][0] == ["npm", "run", "start"]
    assert result["backend_probe"]["status"] == "ready"
    assert result["backend_probe"]["stdout"] == "backend boot ok\n"
    assert result["frontend_probe"]["status"] == "ready"
    assert result["frontend_probe"]["stdout"] == "frontend boot ok\n"

    probe_payload = json.loads((run_root / "reports" / "runtime-server-probes.json").read_text(encoding="utf-8"))
    assert probe_payload["passed"] is True
    assert probe_payload["backend"]["readiness"]["status_code"] == 200
    assert probe_payload["frontend"]["stdout"] == "frontend boot ok\n"


def test_runtime_completion_runner_mount_probe_records_unsupported_browser_environment(tmp_path: Path):
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

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._run_server_probes",
        return_value={
            "attempt_count": 1,
            "passed": True,
            "failure_reason": None,
            "backend": {"passed": True, "status": "ready", "plan": {"command": ["python"]}},
            "frontend": {"passed": True, "status": "ready", "plan": {"command": ["npm"]}},
        },
    ):
        result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site="food",
            run_id="food-run-015",
        )

    assert result["passed"] is False
    assert result["failure_reason"] == "mount_probe_environment_unsupported"
    assert result["mount_probe"]["lightweight_probe"]["wiring_detected"] is True
    assert result["mount_probe"]["browser_probe"]["status"] == "unsupported_environment"

    mount_probe_payload = json.loads((run_root / "reports" / "runtime-mount-probe.json").read_text(encoding="utf-8"))
    assert mount_probe_payload["failure_reason"] == "mount_probe_environment_unsupported"
    assert mount_probe_payload["lightweight_probe"]["mount_file"] == "frontend/src/App.js"


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

    launched = iter([_BackendProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd: next(launched),
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

    launched = iter([_BackendProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd: next(launched),
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

    launched = iter([_BackendProcess(), _FrontendProcess()])

    with patch(
        "chatbot.src.onboarding.runtime_completion_runner._launch_server_process",
        side_effect=lambda command, cwd: next(launched),
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
