from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class BackendBootstrapPlan:
    venv_dir: str
    create_venv_command: list[str] | None
    install_command: list[str] | None
    manifest_source: str | None


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


def build_plan_for_workspace(workspace: Path) -> BackendBootstrapPlan:
    requirements_txt = workspace / "requirements.txt"
    pyproject_toml = workspace / "pyproject.toml"

    if requirements_txt.exists():
        return BackendBootstrapPlan(
            venv_dir=".venv",
            create_venv_command=["python", "-m", "venv", ".venv"],
            install_command=[
                ".venv/bin/python",
                "-m",
                "pip",
                "install",
                "-r",
                "requirements.txt",
            ],
            manifest_source="requirements.txt",
        )

    if pyproject_toml.exists():
        return BackendBootstrapPlan(
            venv_dir=".venv",
            create_venv_command=["python", "-m", "venv", ".venv"],
            install_command=[
                ".venv/bin/python",
                "-m",
                "pip",
                "install",
                ".",
            ],
            manifest_source="pyproject.toml",
        )

    return BackendBootstrapPlan(
        venv_dir=".venv",
        create_venv_command=None,
        install_command=None,
        manifest_source=None,
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


def run_backend_bootstrap(
    *,
    workspace: Path,
    timeout: int = 120,
) -> dict[str, Any]:
    plan = build_plan_for_workspace(workspace)
    result: dict[str, Any] = {
        "workspace": str(workspace),
        "manifest_source": plan.manifest_source,
        "venv_path": str(workspace / plan.venv_dir),
        "create_venv_result": None,
        "install_result": None,
    }

    if plan.create_venv_command:
        result["create_venv_result"] = _execute_command(
            plan.create_venv_command,
            workspace,
            timeout,
        ).to_dict()

    if plan.install_command:
        result["install_result"] = _execute_command(
            plan.install_command,
            workspace,
            timeout,
        ).to_dict()

    return result
