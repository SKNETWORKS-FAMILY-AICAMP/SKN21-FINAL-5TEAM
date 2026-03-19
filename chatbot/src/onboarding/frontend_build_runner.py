from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_TIMEOUT_SECONDS = 120
PACKAGE_MANAGER_LOCKS = {
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
    "npm": "package-lock.json",
}


@dataclass
class CommandResult:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


@dataclass
class BuildPlan:
    package_manager: str
    install_command: list[str] | None
    build_command: list[str] | None


def detect_package_manager(workspace: Path) -> str:
    for manager, lockfile in PACKAGE_MANAGER_LOCKS.items():
        if (workspace / lockfile).exists():
            return manager
    return "npm"


def _read_package_json(workspace: Path) -> dict[str, Any]:
    package_json = workspace / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_plan_for_workspace(workspace: Path) -> BuildPlan:
    manager = detect_package_manager(workspace)
    package_data = _read_package_json(workspace)
    scripts = package_data.get("scripts") or {}
    has_build = isinstance(scripts, dict) and bool(scripts.get("build"))

    install_command = None
    build_command = None
    if manager == "pnpm":
        install_command = ["pnpm", "install"]
        build_command = (
            ["pnpm", "run", "build"] if has_build else ["pnpm", "run", "build"]
        )
    elif manager == "yarn":
        install_command = ["yarn", "install"]
        build_command = ["yarn", "build"] if has_build else ["yarn", "build"]
    else:
        install_command = ["npm", "install"]
        build_command = (
            ["npm", "run", "build"] if has_build else ["npm", "run", "build"]
        )

    return BuildPlan(
        package_manager=manager,
        install_command=install_command,
        build_command=build_command,
    )


def _execute_command(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
) -> CommandResult:
    try:
        proc = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return CommandResult(
            command=list(command),
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=list(command),
            returncode=getattr(exc, "returncode", 124),
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
        )


def classify_frontend_bootstrap_result(
    *,
    install_result: dict[str, Any] | None,
    build_result: dict[str, Any] | None,
) -> dict[str, Any]:
    install_attempted = isinstance(install_result, dict)
    build_attempted = isinstance(build_result, dict)
    install_passed = bool(
        install_attempted
        and install_result.get("returncode") == 0
        and install_result.get("timed_out") is False
    )
    build_passed = bool(
        build_attempted
        and build_result.get("returncode") == 0
        and build_result.get("timed_out") is False
    )

    bootstrap_failure_stage = None
    bootstrap_failure_reason = None
    if install_attempted and not install_passed:
        bootstrap_failure_stage = "install_environment_failed"
        bootstrap_failure_reason = str(
            install_result.get("stderr") or install_result.get("stdout") or "frontend install failed"
        ).strip() or "frontend install failed"
    elif build_attempted and not build_passed:
        bootstrap_failure_stage = "build_environment_failed"
        bootstrap_failure_reason = str(
            build_result.get("stderr") or build_result.get("stdout") or "frontend build failed"
        ).strip() or "frontend build failed"

    return {
        "install_attempted": install_attempted,
        "install_passed": install_passed,
        "build_attempted": build_attempted,
        "build_passed": build_passed,
        "bootstrap_passed": install_passed and build_passed,
        "bootstrap_failure_stage": bootstrap_failure_stage,
        "bootstrap_failure_reason": bootstrap_failure_reason,
    }


def run_frontend_build(
    *,
    workspace: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    plan = build_plan_for_workspace(workspace)
    result: dict[str, Any] = {
        "workspace": str(workspace),
        "package_manager": plan.package_manager,
        "install_result": None,
        "build_result": None,
    }

    if plan.install_command:
        result["install_result"] = _execute_command(
            plan.install_command, workspace, timeout
        ).to_dict()
        install_result = result["install_result"]
        if isinstance(install_result, dict) and (
            install_result.get("returncode") != 0 or install_result.get("timed_out")
        ):
            result["build_skipped"] = True
            result["build_result"] = None
            result.update(
                classify_frontend_bootstrap_result(
                    install_result=install_result,
                    build_result=None,
                )
            )
            return result

    if plan.build_command:
        result["build_result"] = _execute_command(
            plan.build_command, workspace, timeout
        ).to_dict()
    result["build_skipped"] = False
    result.update(
        classify_frontend_bootstrap_result(
            install_result=result.get("install_result") if isinstance(result.get("install_result"), dict) else None,
            build_result=result.get("build_result") if isinstance(result.get("build_result"), dict) else None,
        )
    )

    return result
