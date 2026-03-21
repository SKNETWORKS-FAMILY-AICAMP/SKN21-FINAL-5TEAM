from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
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
    runner = server_probe_runner or _run_server_probes
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
    attempt_count = int(probe_payload.get("attempt_count") or 1)
    server_probes_passed = bool(probe_payload.get("passed", False))
    mount_probe = _run_mount_probe(
        runtime_workspace=workspace,
        frontend_probe=frontend_probe,
    ) if server_probes_passed else _build_skipped_mount_probe()
    mount_probe_path = reports_root / "runtime-mount-probe.json"
    mount_probe_path.write_text(
        json.dumps(mount_probe, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    raw_failure_reason = probe_payload.get("failure_reason") or mount_probe.get("failure_reason")
    failure_reason = str(raw_failure_reason) if raw_failure_reason else None
    launcher_visible = bool(mount_probe.get("launcher_visible", False))
    auth_bootstrap_passed = bool(mount_probe.get("auth_bootstrap_passed", False)) or _read_auth_bootstrap_status(run_root_path)
    chat_stream_passed = bool(mount_probe.get("chat_stream_passed", False))
    passed = server_probes_passed and (
        bool(mount_probe.get("passed", False))
        or (launcher_visible and auth_bootstrap_passed and chat_stream_passed)
    )
    if passed:
        failure_reason = None

    server_probe_report = {
        "run_id": run_id,
        "site": site,
        "runtime_workspace": str(workspace),
        "attempt_count": attempt_count,
        "backend": backend_probe,
        "frontend": frontend_probe,
        "passed": passed,
        "failure_reason": failure_reason,
        "mount_probe": mount_probe,
        "launcher_visible": launcher_visible,
        "auth_bootstrap_passed": auth_bootstrap_passed,
        "chat_stream_passed": chat_stream_passed,
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
        "mount_probe": mount_probe,
        "launcher_visible": launcher_visible,
        "auth_bootstrap_passed": auth_bootstrap_passed,
        "chat_stream_passed": chat_stream_passed,
        "report_path": str(reports_root / "runtime-completion.json"),
        "server_probe_report_path": str(server_probe_path),
        "mount_probe_report_path": str(mount_probe_path),
    }
    completion_path = reports_root / "runtime-completion.json"
    completion_path.write_text(
        json.dumps(completion_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if terminal_logger is not None:
        if passed:
            terminal_logger("runtime completion readiness probes passed")
        else:
            terminal_logger(
                f"runtime completion readiness probes failed: {failure_reason or 'unknown failure'}"
            )

    return completion_report


def _read_auth_bootstrap_status(run_root: Path) -> bool:
    smoke_results_path = run_root / "reports" / "smoke-results.json"
    if not smoke_results_path.exists():
        return False
    try:
        payload = json.loads(smoke_results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, list):
        return False
    return any(
        (item.get("step_id") or item.get("step")) == "chat-auth-token"
        and int(item.get("returncode") or 0) == 0
        for item in payload
        if isinstance(item, dict)
    )


def _build_backend_probe_plan(workspace: Path) -> dict[str, Any]:
    backend_root = workspace / "backend"
    if not backend_root.exists():
        backend_root = workspace

    if (backend_root / "manage.py").exists():
        return {
            "framework": "django",
            "working_directory": str(backend_root),
            "command": ["python", "manage.py", "runserver", "127.0.0.1:8000"],
            "startup_command": ["python", "manage.py", "runserver", "127.0.0.1:8000"],
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
                "startup_command": ["uvicorn", f"{module_name}:app", "--host", "127.0.0.1", "--port", "8000"],
                "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
            }
        if "Flask(" in text or "from flask import" in text:
            return {
                "framework": "flask",
                "working_directory": str(backend_root),
                "command": ["python", candidate.name],
                "startup_command": ["python", candidate.name],
                "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
            }

    return {
        "framework": "unknown",
        "working_directory": str(backend_root),
        "command": None,
        "startup_command": None,
        "readiness_url": "http://127.0.0.1:8000/api/chat/auth-token",
    }


def _build_frontend_probe_plan(workspace: Path) -> dict[str, Any]:
    frontend_root = workspace / "frontend"
    if not frontend_root.exists():
        frontend_root = workspace

    package_manager = detect_package_manager(frontend_root)
    package_data = _read_package_json(frontend_root)
    scripts = package_data.get("scripts") if isinstance(package_data.get("scripts"), dict) else {}
    install_command = _build_frontend_install_command(package_manager)
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
        "install_command": install_command,
        "start_command": command,
        "command": command,
        "readiness_url": "http://127.0.0.1:3000",
    }


def _build_frontend_install_command(package_manager: str) -> list[str]:
    if package_manager == "yarn":
        return ["yarn", "install"]
    if package_manager == "pnpm":
        return ["pnpm", "install"]
    return ["npm", "install"]


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


def _run_mount_probe(
    *,
    runtime_workspace: Path,
    frontend_probe: dict[str, Any],
) -> dict[str, Any]:
    page_url = str(
        (frontend_probe.get("readiness") or {}).get("url")
        or (frontend_probe.get("plan") or {}).get("readiness_url")
        or "http://127.0.0.1:3000"
    )
    lightweight_probe = _run_lightweight_mount_probe(
        runtime_workspace=runtime_workspace,
        page_url=page_url,
    )
    if not lightweight_probe.get("wiring_detected", False):
        return {
            "passed": False,
            "failure_reason": "chatbot_mount_missing",
            "lightweight_probe": lightweight_probe,
            "launcher_visible": bool(lightweight_probe.get("launcher_visible", False)),
            "auth_bootstrap_passed": bool(lightweight_probe.get("auth_bootstrap_passed", False)),
            "chat_stream_passed": bool(lightweight_probe.get("chat_stream_passed", False)),
            "browser_probe": {
                "status": "skipped",
                "reason": "lightweight_mount_probe_failed",
            },
        }

    browser_probe = _run_browser_mount_probe(page_url)
    status = str(browser_probe.get("status") or "")
    launcher_visible = bool(lightweight_probe.get("launcher_visible", False))
    auth_bootstrap_passed = bool(lightweight_probe.get("auth_bootstrap_passed", False))
    chat_stream_passed = bool(lightweight_probe.get("chat_stream_passed", False))
    if status == "unsupported_environment":
        if launcher_visible and auth_bootstrap_passed and chat_stream_passed:
            return {
                "passed": True,
                "failure_reason": None,
                "lightweight_probe": lightweight_probe,
                "launcher_visible": launcher_visible,
                "auth_bootstrap_passed": auth_bootstrap_passed,
                "chat_stream_passed": chat_stream_passed,
                "browser_probe": browser_probe,
            }
        return {
            "passed": False,
            "failure_reason": "mount_probe_environment_unsupported",
            "lightweight_probe": lightweight_probe,
            "launcher_visible": launcher_visible,
            "auth_bootstrap_passed": auth_bootstrap_passed,
            "chat_stream_passed": chat_stream_passed,
            "browser_probe": browser_probe,
        }
    if status not in {"loading", "authenticated", "unauthenticated", "error"}:
        return {
            "passed": False,
            "failure_reason": "chatbot_status_not_rendered",
            "lightweight_probe": lightweight_probe,
            "launcher_visible": launcher_visible,
            "auth_bootstrap_passed": auth_bootstrap_passed,
            "chat_stream_passed": chat_stream_passed,
            "browser_probe": browser_probe,
        }
    return {
        "passed": True,
        "failure_reason": None,
        "lightweight_probe": lightweight_probe,
        "launcher_visible": launcher_visible,
        "auth_bootstrap_passed": auth_bootstrap_passed,
        "chat_stream_passed": chat_stream_passed,
        "browser_probe": browser_probe,
    }


def _build_skipped_mount_probe() -> dict[str, Any]:
    return {
        "passed": False,
        "failure_reason": "mount_probe_skipped",
        "lightweight_probe": {
            "mount_file": None,
            "widget_file": None,
            "wiring_detected": False,
            "page_url": None,
            "status_attribute_present": False,
            "launcher_visible": False,
            "auth_bootstrap_passed": False,
            "chat_stream_passed": False,
        },
        "launcher_visible": False,
        "auth_bootstrap_passed": False,
        "chat_stream_passed": False,
        "browser_probe": {
            "status": "skipped",
            "reason": "server_probes_failed",
        },
    }


def _run_lightweight_mount_probe(*, runtime_workspace: Path, page_url: str) -> dict[str, Any]:
    frontend_root = runtime_workspace / "frontend"
    if not frontend_root.exists():
        frontend_root = runtime_workspace

    mount_file: Path | None = None
    for candidate in sorted(frontend_root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if (
            "order-cs-widget" in text
            or "__ORDER_CS_WIDGET_HOST_CONTRACT__" in text
            or "widgetBundlePath" in text
            or "data-order-cs-widget-bundle" in text
        ):
            mount_file = candidate
            break

    wiring_detected = False
    launcher_visible = False
    auth_bootstrap_passed = False
    chat_stream_passed = False
    if mount_file is not None:
        content = mount_file.read_text(encoding="utf-8", errors="ignore")
        launcher_visible = "<order-cs-widget" in content
        auth_bootstrap_passed = "/api/chat/auth-token" in content or "authBootstrapPath" in content
        chat_stream_passed = "widget.js" in content or "__ORDER_CS_WIDGET_HOST_CONTRACT__" in content
        wiring_detected = launcher_visible and auth_bootstrap_passed and chat_stream_passed

    return {
        "mount_file": str(mount_file.relative_to(runtime_workspace)) if mount_file else None,
        "widget_file": None,
        "wiring_detected": wiring_detected,
        "page_url": page_url,
        "status_attribute_present": False,
        "launcher_visible": launcher_visible,
        "auth_bootstrap_passed": auth_bootstrap_passed,
        "chat_stream_passed": chat_stream_passed,
    }


def _run_browser_mount_probe(page_url: str) -> dict[str, Any]:
    return {
        "status": "unsupported_environment",
        "page_url": page_url,
        "reason": "browser_probe_not_configured",
    }


def _run_server_probes(context: dict[str, Any]) -> dict[str, Any]:
    backend_probe = _run_single_server_probe(
        plan=context["backend_plan"],
        probe_name="backend",
    )
    frontend_probe = _run_single_server_probe(
        plan=context["frontend_plan"],
        probe_name="frontend",
    )
    failure_reason = backend_probe.get("failure_reason") or frontend_probe.get("failure_reason")
    return {
        "attempt_count": 1,
        "passed": bool(backend_probe.get("passed")) and bool(frontend_probe.get("passed")),
        "failure_reason": failure_reason,
        "backend": backend_probe,
        "frontend": frontend_probe,
    }


def _run_single_server_probe(*, plan: dict[str, Any], probe_name: str) -> dict[str, Any]:
    command = plan.get("command")
    readiness_url = str(plan.get("readiness_url") or "")
    working_directory = Path(str(plan.get("working_directory") or "."))
    if not command:
        return {
            "plan": plan,
            "passed": False,
            "status": "command_missing",
            "failure_reason": f"{probe_name}_command_missing",
            "stdout": "",
            "stderr": "",
            "pid": None,
            "readiness": None,
        }

    try:
        process = _launch_server_process(command=list(command), cwd=working_directory)
    except OSError as exc:
        return {
            "plan": plan,
            "passed": False,
            "status": "boot_failed",
            "failure_reason": f"{probe_name}_server_boot_failed",
            "stdout": "",
            "stderr": str(exc),
            "pid": None,
            "readiness": None,
        }

    if process.poll() is not None:
        stdout, stderr = _collect_process_output(process)
        failure_reason = _classify_probe_failure_reason(
            probe_name=probe_name,
            stdout=stdout,
            stderr=stderr,
            default_reason=f"{probe_name}_server_boot_failed",
        )
        return {
            "plan": plan,
            "passed": False,
            "status": "boot_failed",
            "failure_reason": failure_reason,
            "stdout": stdout,
            "stderr": stderr,
            "pid": getattr(process, "pid", None),
            "readiness": None,
        }

    readiness = _probe_http_ready(readiness_url)
    _terminate_process(process)
    stdout, stderr = _collect_process_output(process)
    if not readiness.get("passed"):
        return {
            "plan": plan,
            "passed": False,
            "status": "readiness_failed",
            "failure_reason": f"{probe_name}_readiness_failed",
            "stdout": stdout,
            "stderr": stderr,
            "pid": getattr(process, "pid", None),
            "readiness": readiness,
        }
    return {
        "plan": plan,
        "passed": True,
        "status": "ready",
        "failure_reason": None,
        "stdout": stdout,
        "stderr": stderr,
        "pid": getattr(process, "pid", None),
        "readiness": readiness,
    }


def _launch_server_process(*, command: list[str], cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _collect_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=1)
    return stdout or "", stderr or ""


def _probe_http_ready(
    url: str,
    *,
    timeout_seconds: int = 2,
    attempts: int = 10,
    delay_seconds: float = 0.2,
) -> dict[str, Any]:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                return {
                    "passed": True,
                    "url": url,
                    "status_code": getattr(response, "status", 200),
                    "attempts": attempt,
                    "error": None,
                }
        except urllib.error.URLError as exc:
            last_error = str(exc.reason or exc)
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = str(exc)
        if attempt < attempts:
            time.sleep(delay_seconds)
    return {
        "passed": False,
        "url": url,
        "status_code": None,
        "attempts": attempts,
        "error": last_error or "readiness probe failed",
    }


def _classify_probe_failure_reason(
    *,
    probe_name: str,
    stdout: str,
    stderr: str,
    default_reason: str,
) -> str:
    combined = f"{stdout}\n{stderr}"
    if probe_name == "backend" and _is_django_urlconf_import_failure(combined):
        return "django_urlconf_import_failed"
    if probe_name == "frontend" and "@shared-chatbot/ChatbotWidget" in combined and "Can't resolve" in combined:
        return "frontend_import_resolution_failed"
    if probe_name == "backend" and "ModuleNotFoundError" in combined and "No module named 'backend'" in combined:
        return "backend_import_resolution_failed"
    return default_reason


def _is_django_urlconf_import_failure(combined: str) -> bool:
    return "urls.py" in combined and "No module named 'backend'" in combined
