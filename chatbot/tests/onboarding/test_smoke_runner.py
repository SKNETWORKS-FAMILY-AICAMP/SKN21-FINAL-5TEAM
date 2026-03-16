import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.smoke_contract import SmokeTestPlan, SmokeTestStep
from chatbot.src.onboarding.smoke_runner import load_smoke_plan, run_smoke_tests


def test_load_smoke_plan_reads_manifest_steps(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {
                    "smoke": [
                        "smoke-tests/login.sh",
                        "smoke-tests/chat_auth_token.sh",
                    ]
                },
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = load_smoke_plan(run_root)

    assert plan == SmokeTestPlan(
        steps=[
            "smoke-tests/login.sh",
            "smoke-tests/chat_auth_token.sh",
        ]
    )


def test_run_smoke_tests_executes_scripts_and_collects_results(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text("#!/bin/sh\necho smoke-ok\n", encoding="utf-8")
    script_path.chmod(0o755)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(steps=["smoke-tests/login.sh"]),
    )

    assert len(results) == 1
    assert results[0]["step"] == "smoke-tests/login.sh"
    assert results[0]["returncode"] == 0
    assert results[0]["stdout"].strip() == "smoke-ok"


def test_run_smoke_tests_executes_relative_run_root_from_different_cwd(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    run_root = project_root / "generated" / "food" / "food-run-001"
    runtime_workspace = project_root / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text("#!/bin/sh\necho smoke-ok\n", encoding="utf-8")
    script_path.chmod(0o755)

    monkeypatch.chdir(project_root)

    results = run_smoke_tests(
        run_root=Path("generated") / "food" / "food-run-001",
        runtime_workspace=Path("runtime") / "food" / "food-run-001" / "workspace",
        plan=SmokeTestPlan(steps=["smoke-tests/login.sh"]),
    )

    assert len(results) == 1
    assert results[0]["returncode"] == 0
    assert results[0]["stdout"].strip() == "smoke-ok"


def test_run_smoke_tests_reports_missing_script(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"

    runtime_workspace.mkdir(parents=True)
    run_root.mkdir(parents=True)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(steps=["smoke-tests/missing.sh"]),
    )

    assert results[0]["returncode"] == 127
    assert "missing.sh" in results[0]["stderr"]


def test_load_smoke_plan_reads_step_metadata(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {
                    "smoke": [
                        {
                            "id": "chat-auth",
                            "script": "smoke-tests/chat_auth_token.sh",
                            "env": {"EXPECTED_STATUS": "200"},
                            "timeout_seconds": 5,
                            "required": True,
                            "category": "auth",
                        }
                    ]
                },
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = load_smoke_plan(run_root)

    assert plan == SmokeTestPlan(
        steps=[
            SmokeTestStep(
                id="chat-auth",
                script="smoke-tests/chat_auth_token.sh",
                env={"EXPECTED_STATUS": "200"},
                timeout_seconds=5,
                required=True,
                category="auth",
            )
        ]
    )


def test_run_smoke_tests_includes_timeout_and_env(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$EXPECTED_VALUE\"\n",
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(
            steps=[
                SmokeTestStep(
                    id="login",
                    script="smoke-tests/login.sh",
                    env={"EXPECTED_VALUE": "ok"},
                    timeout_seconds=1,
                    required=True,
                    category="auth",
                )
            ]
        ),
    )

    assert results[0]["step"] == "smoke-tests/login.sh"
    assert results[0]["step_id"] == "login"
    assert results[0]["required"] is True
    assert results[0]["category"] == "auth"
    assert results[0]["timed_out"] is False
    assert results[0]["stdout"].strip() == "ok"
