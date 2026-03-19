from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .frontend_build_runner import detect_package_manager


def run_runtime_completion(
    *,
    run_root: str | Path,
    runtime_workspace: str | Path,
    site: str,
    run_id: str,
    terminal_logger: Callable[[str], None] | None = None,
    server_probe_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_root_path = Path(run_root)
    workspace = Path(runtime_workspace)
    reports_root = run_root_path / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)

    backend_plan = _build_backend_probe_plan(workspace)
    frontend_plan = _build_frontend_probe_plan(workspace)
    runner = server_probe_runner or _run_server_probes_placeholder
    probe_payload = runner(
        {
            "site": site,
            "run_id": run_id,
            "runtime_workspace": str(workspace),
            "backend_plan": backend_plan,
            "frontend_plan": frontend_plan,
        }
    )

    backend_probe = probe_payload.get("backend") or {
        "plan": backend_plan,
        "passed": False,
        "status": "not_started",
    }
    frontend_probe = probe_payload.get("frontend") or {
        "plan": frontend_plan,
        "passed": False,
        "status": "not_started",
    }
    failure_reason = str(
        probe_payload.get("failure_reason")
        or "runtime_server_probes_not_implemented"
    )
    attempt_count = int(probe_payload.get("attempt_count") or 1)
    passed = bool(probe_payload.get("passed", False))

    server_probe_report = {
        "run_id": run_id,
        "site": site,
        "runtime_workspace": str(workspace),
        "attempt_count": attempt_count,
        "backend": backend_probe,
        "frontend": frontend_probe,
        "passed": passed,
        "failure_reason": failure_reason,
    }
    server_probe_path = reports_root / "runtime-server-probes.json"
    server_probe_path.write_text(
        json.dumps(server_probe_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    completion_report = {
        "run_id": run_id,
        "site": site,
        "runtime_workspace": str(workspace),
        "attempt_count": attempt_count,
        "passed": passed,
        "failure_reason": failure_reason,
        "backend_probe": backend_probe,
        "frontend_probe": frontend_probe,
        "report_path": str(reports_root / "runtime-completion.json"),
        "server_probe_report_path": str(server_probe_path),
    }
    completion_path = reports_root / "runtime-completion.json"
    completion_path.write_text(
        json.dumps(completion_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if terminal_logger is not None:
        terminal_logger(
            f"runtime completion placeholder recorded failure: {failure_reason}"
        )

    return completion_report


def _build_backend_probe_plan(workspace: Path) -> dict[str, Any]:
    backend_root = workspace / "backend"
    if not backend_root.exists():
        backend_root = workspace

    if (backend_root / "manage.py").exists():
        return {
            "framework": "django",
            "working_directory": str(backend_root),
            "command": ["python", "manage.py", "runserver", "127.0.0.1:8000"],
            "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
        }

    for candidate in [backend_root / "main.py", backend_root / "app.py"]:
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text or "from fastapi import" in text:
            module_name = candidate.stem
            return {
                "framework": "fastapi",
                "working_directory": str(backend_root),
                "command": ["uvicorn", f"{module_name}:app", "--host", "127.0.0.1", "--port", "8000"],
                "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
            }
        if "Flask(" in text or "from flask import" in text:
            return {
                "framework": "flask",
                "working_directory": str(backend_root),
                "command": ["python", candidate.name],
                "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
            }

    return {
        "framework": "unknown",
        "working_directory": str(backend_root),
        "command": None,
        "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
    }


def _build_frontend_probe_plan(workspace: Path) -> dict[str, Any]:
    frontend_root = workspace / "frontend"
    if not frontend_root.exists():
        frontend_root = workspace

    package_manager = detect_package_manager(frontend_root)
    package_data = _read_package_json(frontend_root)
    scripts = package_data.get("scripts") if isinstance(package_data.get("scripts"), dict) else {}
    command: list[str] | None = None
    if scripts.get("dev"):
        command = _build_package_manager_script_command(package_manager, "dev")
    elif scripts.get("start"):
        command = _build_package_manager_script_command(package_manager, "start")
    elif scripts.get("build"):
        command = _build_package_manager_script_command(package_manager, "build")

    return {
        "package_manager": package_manager,
        "working_directory": str(frontend_root),
        "command": command,
        "readiness_url": "http://127.0.0.1:3000",
    }


def _build_package_manager_script_command(package_manager: str, script_name: str) -> list[str]:
    if package_manager == "yarn":
        return ["yarn", script_name]
    if package_manager == "pnpm":
        return ["pnpm", script_name]
    return ["npm", "run", script_name]


def _read_package_json(frontend_root: Path) -> dict[str, Any]:
    package_json = frontend_root / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _run_server_probes_placeholder(context: dict[str, Any]) -> dict[str, Any]:
    return {
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
    }
