import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.frontend_build_runner import (
    build_plan_for_workspace,
    classify_frontend_bootstrap_result,
)


def test_build_plan_prefers_package_manager_lockfiles(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "package-lock.json").write_text("{}", encoding="utf-8")
    (workspace / "package.json").write_text("{}", encoding="utf-8")

    plan = build_plan_for_workspace(workspace)

    assert plan.package_manager == "npm"
    assert plan.install_command == ["npm", "install"]
    assert plan.build_command == ["npm", "run", "build"]


def test_classify_frontend_bootstrap_result_marks_install_failure_first():
    summary = classify_frontend_bootstrap_result(
        install_result={
            "command": ["npm", "install"],
            "returncode": 1,
            "stdout": "",
            "stderr": "npm install failed",
            "timed_out": False,
        },
        build_result=None,
    )

    assert summary["install_passed"] is False
    assert summary["build_attempted"] is False
    assert summary["build_passed"] is False
    assert summary["bootstrap_passed"] is False
    assert summary["bootstrap_failure_stage"] == "install_environment_failed"
    assert summary["bootstrap_failure_reason"] == "npm install failed"


def test_classify_frontend_bootstrap_result_marks_build_failure_separately():
    summary = classify_frontend_bootstrap_result(
        install_result={
            "command": ["npm", "install"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
        },
        build_result={
            "command": ["npm", "run", "build"],
            "returncode": 1,
            "stdout": "",
            "stderr": "build failed",
            "timed_out": False,
        },
    )

    assert summary["install_passed"] is True
    assert summary["build_attempted"] is True
    assert summary["build_passed"] is False
    assert summary["bootstrap_passed"] is False
    assert summary["bootstrap_failure_stage"] == "build_environment_failed"
    assert summary["bootstrap_failure_reason"] == "build failed"
