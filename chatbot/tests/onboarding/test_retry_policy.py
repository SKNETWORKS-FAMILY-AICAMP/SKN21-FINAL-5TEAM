import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding import orchestrator as orchestrator_module
from chatbot.src.onboarding.agent_orchestrator import AgentOrchestrator
from chatbot.src.onboarding.agent_contracts import RunState
from chatbot.src.onboarding.orchestrator import _run_validation_with_retries
from chatbot.src.onboarding.role_runner import RoleRunner
from chatbot.src.onboarding.smoke_contract import SmokeTestPlan, SmokeTestStep


def _role_runner(should_retry: bool) -> RoleRunner:
    return RoleRunner(
        responders={
            "Diagnostician": lambda context: {
                "claim": "diagnose retry policy",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "retry_validation" if should_retry else "request_human_review",
                "blocking_issue": "none" if should_retry else "structural failure",
                "metadata": {"should_retry": should_retry},
            }
        }
    )


def test_retry_policy_does_not_retry_missing_script_failure(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        return [
            {
                "step": "smoke-tests/missing.sh",
                "step_id": "missing",
                "returncode": 127,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "",
                "stderr": "Smoke script not found: /tmp/missing.sh",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-001")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-001",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="missing", script="smoke-tests/missing.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
    )

    assert results[0]["returncode"] == 127
    assert smoke_calls["count"] == 1
    assert agent.retry_count == 0
    assert agent.state == RunState.HUMAN_REVIEW_REQUIRED


def test_retry_policy_retries_transient_timeout_once(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    smoke_calls = {"count": 0}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        if smoke_calls["count"] == 1:
            return [
                {
                    "step": "smoke-tests/login.sh",
                    "step_id": "login",
                    "returncode": 124,
                    "required": True,
                    "category": "auth",
                    "timed_out": True,
                    "stdout": "",
                    "stderr": "",
                }
            ]
        return [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-001")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-001",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="login", script="smoke-tests/login.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
    )

    assert smoke_calls["count"] == 2
    assert agent.retry_count == 1
    assert agent.state == RunState.VALIDATING
    assert results[0]["returncode"] == 0


def test_validation_retries_starts_runtime_servers_before_smoke_and_tears_down(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-002"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-002" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    call_order: list[str] = []

    def fake_start_validation_runtime_servers(*, runtime_workspace, run_root):
        call_order.append("start")
        return {
            "backend": {"passed": True, "status": "ready"},
            "frontend": {"passed": True, "status": "ready"},
        }

    def fake_stop_validation_runtime_servers(server_state):
        call_order.append("stop")

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        call_order.append("smoke")
        return [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._start_validation_runtime_servers", fake_start_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._stop_validation_runtime_servers", fake_stop_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-002")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-002",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="login", script="smoke-tests/login.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
    )

    assert results[0]["returncode"] == 0
    assert call_order == ["start", "smoke", "stop"]


def test_validation_retries_returns_runtime_server_failures_without_running_smoke(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-003"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-003" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    smoke_calls = {"count": 0}

    def fake_start_validation_runtime_servers(*, runtime_workspace, run_root):
        return {
            "backend": {
                "passed": False,
                "status": "readiness_failed",
                "failure_reason": "backend_readiness_failed",
                "stderr": "Connection refused",
            },
            "frontend": {"passed": True, "status": "ready"},
        }

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        smoke_calls["count"] += 1
        return []

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._start_validation_runtime_servers", fake_start_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._stop_validation_runtime_servers", lambda server_state: None)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-003")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-003",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="login", script="smoke-tests/login.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=False),
    )

    assert smoke_calls["count"] == 0
    assert results[0]["step_id"] == "validation-backend-runtime"
    assert results[0]["returncode"] == 1
    assert "backend_readiness_failed" in results[0]["stderr"]


def test_validation_retries_restarts_servers_after_llm_runtime_repair(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-004"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-004" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    calls = {"start": 0, "smoke": 0, "llm": 0}

    def fake_start_validation_runtime_servers(*, runtime_workspace, run_root):
        calls["start"] += 1
        if calls["start"] == 1:
            return {
                "backend": {
                    "passed": False,
                    "status": "readiness_failed",
                    "failure_reason": "backend_readiness_failed",
                    "stderr": "ModuleNotFoundError: No module named 'backend'",
                },
                "frontend": {"passed": True, "status": "ready"},
            }
        return {
            "backend": {"passed": True, "status": "ready"},
            "frontend": {"passed": True, "status": "ready"},
        }

    def fake_attempt_llm_runtime_repair_cycle(**kwargs):
        calls["llm"] += 1
        return {"applied": True, "patch_path": str(run_root / "patches" / "runtime-repair.patch")}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        calls["smoke"] += 1
        return [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._start_validation_runtime_servers", fake_start_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._stop_validation_runtime_servers", lambda server_state: None)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._attempt_llm_runtime_repair_cycle", fake_attempt_llm_runtime_repair_cycle)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-004")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-004",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="login", script="smoke-tests/login.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
        llm_runtime_repair_factory=lambda: object(),
        llm_provider="openai",
        llm_model="gpt-5.2",
    )

    assert results[0]["returncode"] == 0
    assert calls == {"start": 2, "smoke": 1, "llm": 1}


def test_validation_retries_reruns_smoke_after_llm_runtime_repair(tmp_path: Path, monkeypatch):
    run_root = tmp_path / "generated" / "food" / "food-run-005"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-005" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    calls = {"start": 0, "stop": 0, "smoke": 0, "llm": 0}

    def fake_start_validation_runtime_servers(*, runtime_workspace, run_root):
        calls["start"] += 1
        return {
            "backend": {"passed": True, "status": "ready"},
            "frontend": {"passed": True, "status": "ready"},
        }

    def fake_stop_validation_runtime_servers(server_state):
        calls["stop"] += 1

    def fake_attempt_llm_runtime_repair_cycle(**kwargs):
        calls["llm"] += 1
        return {"applied": True, "patch_path": str(run_root / "patches" / "runtime-repair.patch")}

    def fake_run_smoke_tests(*, run_root, runtime_workspace, plan):
        calls["smoke"] += 1
        if calls["smoke"] == 1:
            return [
                {
                    "step": "smoke-tests/chat-auth.sh",
                    "step_id": "chat-auth-token",
                    "returncode": 1,
                    "required": True,
                    "category": "auth",
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "backend import mismatch",
                }
            ]
        return [
            {
                "step": "smoke-tests/chat-auth.sh",
                "step_id": "chat-auth-token",
                "returncode": 0,
                "required": True,
                "category": "auth",
                "timed_out": False,
                "stdout": "ok",
                "stderr": "",
            }
        ]

    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._start_validation_runtime_servers", fake_start_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._stop_validation_runtime_servers", fake_stop_validation_runtime_servers)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator._attempt_llm_runtime_repair_cycle", fake_attempt_llm_runtime_repair_cycle)
    monkeypatch.setattr("chatbot.src.onboarding.orchestrator.run_smoke_tests", fake_run_smoke_tests)

    agent = AgentOrchestrator(run_id="food-run-005")
    agent.state = RunState.VALIDATING

    results = _run_validation_with_retries(
        run_id="food-run-005",
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=SmokeTestPlan(steps=[SmokeTestStep(id="chat-auth-token", script="smoke-tests/chat-auth.sh")]),
        agent=agent,
        bridge=None,
        role_runner=_role_runner(should_retry=True),
        llm_runtime_repair_factory=lambda: object(),
        llm_provider="openai",
        llm_model="gpt-5.2",
    )

    assert results[0]["returncode"] == 0
    assert calls["llm"] == 1
    assert calls["smoke"] == 2
    assert calls["start"] == 2
    assert calls["stop"] >= 1


def test_launch_validation_runtime_server_terminates_before_collecting_output_on_readiness_failure(
    tmp_path: Path, monkeypatch
):
    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

    process = FakeProcess()

    def fake_terminate_process(proc):
        proc.terminated = True
        proc.returncode = 0

    def fake_collect_process_output(proc):
        assert proc.terminated is True
        return "", "server stderr"

    monkeypatch.setattr(orchestrator_module, "_launch_server_process", lambda **kwargs: process)
    monkeypatch.setattr(
        orchestrator_module,
        "_probe_http_ready",
        lambda *args, **kwargs: {
            "passed": False,
            "url": "http://127.0.0.1:8000/api/chat/auth-token",
            "status_code": None,
            "attempts": 10,
            "error": "Not Found",
        },
    )
    monkeypatch.setattr(orchestrator_module, "_terminate_process", fake_terminate_process)
    monkeypatch.setattr(orchestrator_module, "_collect_process_output", fake_collect_process_output)

    result = orchestrator_module._launch_validation_runtime_server(
        plan={
            "command": ["python", "manage.py", "runserver", "127.0.0.1:8000"],
            "working_directory": str(tmp_path),
            "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
        },
        probe_name="backend",
    )

    assert result["passed"] is False
    assert result["status"] == "readiness_failed"
    assert result["process"] is None


def test_launch_validation_runtime_server_reads_file_backed_frontend_logs_on_readiness_failure(
    tmp_path: Path, monkeypatch
):
    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 55443
            self.returncode = None
            self.stdout = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.stdout.write("vite starting\n")
            self.stderr.write("port probe failed\n")

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
            raise AssertionError("communicate should not be used for file-backed frontend logs")

    process = FakeProcess()

    monkeypatch.setattr(orchestrator_module, "_launch_server_process", lambda **kwargs: process)
    monkeypatch.setattr(
        orchestrator_module,
        "_probe_http_ready",
        lambda *args, **kwargs: {
            "passed": False,
            "url": "http://127.0.0.1:3000",
            "status_code": None,
            "attempts": 10,
            "error": "Connection refused",
        },
    )

    result = orchestrator_module._launch_validation_runtime_server(
        plan={
            "command": ["npm", "run", "dev"],
            "working_directory": str(tmp_path),
            "readiness_url": "http://127.0.0.1:3000",
        },
        probe_name="frontend",
    )

    assert result["passed"] is False
    assert result["status"] == "readiness_failed"
    assert result["process"] is None
    assert result["stdout"] == "vite starting\n"
    assert result["stderr"] == "port probe failed\n"
