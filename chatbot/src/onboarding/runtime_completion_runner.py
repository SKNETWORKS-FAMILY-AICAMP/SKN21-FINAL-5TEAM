from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .frontend_build_runner import detect_package_manager
from .shared_chatbot_assets import resolve_shared_chatbot_assets


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
    port_map = {
        "backend": 8000,
        "chatbot": 8100,
        "frontend": 3000,
    }
    if server_probe_runner is None:
        port_map = {
            "backend": _reserve_loopback_port(),
            "chatbot": _reserve_loopback_port(),
            "frontend": _reserve_loopback_port(),
        }

    backend_base_url = f"http://127.0.0.1:{port_map['backend']}"
    chatbot_base_url = f"http://127.0.0.1:{port_map['chatbot']}"
    backend_plan = _build_backend_probe_plan(workspace, port=port_map["backend"])
    chatbot_plan = _build_chatbot_probe_plan(
        workspace,
        site=site,
        port=port_map["chatbot"],
        backend_base_url=backend_base_url,
    )
    frontend_plan = _build_frontend_probe_plan(
        workspace,
        chatbot_plan=chatbot_plan,
        port=port_map["frontend"],
    )
    probe_context = {
        "site": site,
        "run_id": run_id,
        "runtime_workspace": str(workspace),
        "backend_plan": backend_plan,
        "chatbot_plan": chatbot_plan,
        "frontend_plan": frontend_plan,
    }
    live_processes: dict[str, subprocess.Popen[str]] = {}
    if server_probe_runner is None:
        probe_payload, live_processes = _run_server_probes_with_live_processes(probe_context)
    else:
        probe_payload = server_probe_runner(probe_context)

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
    chatbot_probe = probe_payload.get("chatbot") or {
        "plan": chatbot_plan,
        "passed": False,
        "status": "not_started",
    }
    attempt_count = int(probe_payload.get("attempt_count") or 1)
    server_probes_passed = bool(probe_payload.get("passed", False))
    try:
        contract_probe = _build_skipped_contract_probe("server_probes_failed")
        if server_probes_passed:
            contract_probe = _run_runtime_contract_probe(
                run_root=run_root_path,
                site=site,
                backend_base_url=backend_base_url,
                chatbot_base_url=chatbot_base_url,
            )
        mount_probe = _run_mount_probe(
            runtime_workspace=workspace,
            frontend_probe=frontend_probe,
        ) if server_probes_passed else _build_skipped_mount_probe()
    finally:
        if live_processes:
            _finalize_live_server_probe_outputs(probe_payload=probe_payload, live_processes=live_processes)
    mount_probe_path = reports_root / "runtime-mount-probe.json"
    mount_probe_path.write_text(
        json.dumps(mount_probe, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    raw_failure_reason = probe_payload.get("failure_reason") or mount_probe.get("failure_reason")
    if contract_probe.get("status") not in {"skipped", "not_configured"}:
        raw_failure_reason = raw_failure_reason or contract_probe.get("failure_reason")
    failure_reason = str(raw_failure_reason) if raw_failure_reason else None
    passed = (
        server_probes_passed
        and bool(mount_probe.get("passed", False))
        and (contract_probe.get("status") in {"skipped", "not_configured"} or bool(contract_probe.get("passed", False)))
    )

    server_probe_report = {
        "run_id": run_id,
        "site": site,
        "runtime_workspace": str(workspace),
        "attempt_count": attempt_count,
        "backend": backend_probe,
        "chatbot": chatbot_probe,
        "frontend": frontend_probe,
        "contract_probe": contract_probe,
        "passed": passed,
        "failure_reason": failure_reason,
        "mount_probe": mount_probe,
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
        "chatbot_probe": chatbot_probe,
        "frontend_probe": frontend_probe,
        "contract_probe": contract_probe,
        "mount_probe": mount_probe,
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


def _reserve_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _build_backend_probe_plan(
    workspace: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> dict[str, Any]:
    backend_root = workspace / "backend"
    if not backend_root.exists():
        backend_root = workspace
    backend_base_url = f"http://{host}:{port}"
    backend_socket = f"{host}:{port}"

    if (backend_root / "manage.py").exists():
        python_command = _resolve_backend_python_command(backend_root)
        return {
            "framework": "django",
            "working_directory": str(backend_root),
            "command": [python_command, "manage.py", "runserver", backend_socket, "--noreload"],
            "startup_command": [python_command, "manage.py", "runserver", backend_socket, "--noreload"],
            "readiness_method": "POST",
            "readiness_expected_statuses": [200, 401],
            "readiness_timeout_seconds": 3,
            "readiness_attempts": 30,
            "readiness_delay_seconds": 0.5,
            "readiness_url": f"{backend_base_url}/api/chat/auth-token",
        }

    for candidate in [backend_root / "main.py", backend_root / "app.py"]:
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text or "from fastapi import" in text:
            module_name = candidate.stem
            if "uvicorn.run(" not in text and "__main__" not in text:
                return {
                    "framework": "fastapi",
                    "working_directory": str(backend_root),
                    "command": None,
                    "startup_command": None,
                    "readiness_url": f"{backend_base_url}/api/chat/auth-token",
                }
            return {
                "framework": "fastapi",
                "working_directory": str(backend_root),
                "command": ["uvicorn", f"{module_name}:app", "--host", host, "--port", str(port)],
                "startup_command": ["uvicorn", f"{module_name}:app", "--host", host, "--port", str(port)],
                "readiness_url": f"{backend_base_url}/api/chat/auth-token",
            }
        if "Flask(" in text or "from flask import" in text:
            if "app.run(" not in text and "__main__" not in text:
                return {
                    "framework": "flask",
                    "working_directory": str(backend_root),
                    "command": None,
                    "startup_command": None,
                    "readiness_url": f"{backend_base_url}/api/chat/auth-token",
                }
            return {
                "framework": "flask",
                "working_directory": str(backend_root),
                "command": ["python", candidate.name],
                "startup_command": ["python", candidate.name],
                "readiness_url": f"{backend_base_url}/api/chat/auth-token",
            }

    return {
        "framework": "unknown",
        "working_directory": str(backend_root),
        "command": None,
        "startup_command": None,
        "readiness_url": f"{backend_base_url}/api/chat/auth-token",
    }


def _build_frontend_probe_plan(
    workspace: Path,
    *,
    chatbot_plan: dict[str, Any] | None = None,
    host: str = "127.0.0.1",
    port: int = 3000,
) -> dict[str, Any]:
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
        "environment": _build_frontend_runtime_environment(chatbot_plan=chatbot_plan, port=port),
        "readiness_url": f"http://{host}:{port}",
    }


def _resolve_backend_python_command(backend_root: Path) -> str:
    candidates = [
        backend_root / ".venv" / "bin" / "python",
        backend_root / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.absolute())

    python_path = getattr(sys, "executable", "") or ""
    if python_path:
        return python_path

    for executable in ("python3", "python"):
        resolved = shutil.which(executable)
        if resolved:
            return resolved
    return "python3"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _build_chatbot_probe_plan(
    workspace: Path,
    *,
    site: str,
    host: str = "127.0.0.1",
    port: int = 8100,
    backend_base_url: str = "http://127.0.0.1:8000",
) -> dict[str, Any]:
    return {
        "working_directory": str(_repo_root()),
        "command": [
            sys.executable,
            "-m",
            "uvicorn",
            "chatbot.server_fastapi:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        "start_command": [
            sys.executable,
            "-m",
            "uvicorn",
            "chatbot.server_fastapi:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        "environment": _build_chatbot_runtime_environment(site=site, backend_base_url=backend_base_url),
        "readiness_url": f"http://{host}:{port}/health",
        "readiness_method": "GET",
        "readiness_expected_statuses": [200],
        "readiness_timeout_seconds": 3,
        "readiness_attempts": 30,
        "readiness_delay_seconds": 0.5,
    }


def _build_chatbot_runtime_environment(
    *,
    site: str,
    backend_base_url: str = "http://127.0.0.1:8000",
) -> dict[str, str]:
    normalized_site = str(site or "").strip().lower()
    environment: dict[str, str] = {}
    if normalized_site == "food":
        environment["FOOD_API_URL"] = backend_base_url
    elif normalized_site == "bilyeo":
        environment["BILYEO_API_URL"] = backend_base_url
    else:
        environment["BACKEND_API_URL"] = backend_base_url
    return environment


def _build_frontend_runtime_environment(
    *,
    chatbot_plan: dict[str, Any] | None = None,
    port: int = 3000,
) -> dict[str, str]:
    chatbot_api_base = str(
        (chatbot_plan or {}).get("readiness_url") or "http://127.0.0.1:8100/health"
    ).removesuffix("/health")
    return {
        "PORT": str(port),
        "BROWSER": "none",
        "REACT_APP_CHATBOT_API_BASE": chatbot_api_base,
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
        "chatbot": {
            "plan": context["chatbot_plan"],
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
            "browser_probe": {
                "status": "skipped",
                "reason": "lightweight_mount_probe_failed",
            },
        }

    browser_probe = _run_browser_mount_probe(page_url)
    status = str(browser_probe.get("status") or "")
    if status == "unsupported_environment":
        if lightweight_probe.get("status_attribute_present", False):
            return {
                "passed": True,
                "failure_reason": None,
                "lightweight_probe": lightweight_probe,
                "browser_probe": browser_probe,
            }
        return {
            "passed": False,
            "failure_reason": "mount_probe_environment_unsupported",
            "lightweight_probe": lightweight_probe,
            "browser_probe": browser_probe,
        }
    if status not in {"loading", "authenticated", "unauthenticated", "error"}:
        return {
            "passed": False,
            "failure_reason": "chatbot_status_not_rendered",
            "lightweight_probe": lightweight_probe,
            "browser_probe": browser_probe,
        }
    return {
        "passed": True,
        "failure_reason": None,
        "lightweight_probe": lightweight_probe,
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
        },
        "browser_probe": {
            "status": "skipped",
            "reason": "server_probes_failed",
        },
    }


def _build_skipped_contract_probe(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "passed": False,
        "failure_reason": reason,
        "chat_auth": None,
        "chatbot_stream": None,
    }


def _run_lightweight_mount_probe(*, runtime_workspace: Path, page_url: str) -> dict[str, Any]:
    frontend_root = runtime_workspace / "frontend"
    if not frontend_root.exists():
        frontend_root = runtime_workspace

    mount_file: Path | None = None
    widget_file: Path | None = None
    for candidate in sorted(frontend_root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.name.startswith("SharedChatbotWidget"):
            widget_file = widget_file or candidate
            continue
        if candidate.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if "SharedChatbotWidget" in text:
            mount_file = mount_file or candidate

    wiring_detected = False
    if mount_file is not None:
        content = mount_file.read_text(encoding="utf-8", errors="ignore")
        wiring_detected = "import SharedChatbotWidget" in content and "<SharedChatbotWidget" in content

    status_attribute_present = False
    if widget_file is not None:
        widget_content = widget_file.read_text(encoding="utf-8", errors="ignore")
        status_attribute_present = "data-chatbot-status" in widget_content

    return {
        "mount_file": str(mount_file.relative_to(runtime_workspace)) if mount_file else None,
        "widget_file": str(widget_file.relative_to(runtime_workspace)) if widget_file else None,
        "wiring_detected": wiring_detected,
        "page_url": page_url,
        "status_attribute_present": status_attribute_present,
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
    chatbot_probe = _run_single_server_probe(
        plan=context["chatbot_plan"],
        probe_name="chatbot",
    )
    frontend_probe = _run_single_server_probe(
        plan=context["frontend_plan"],
        probe_name="frontend",
    )
    failure_reason = (
        backend_probe.get("failure_reason")
        or chatbot_probe.get("failure_reason")
        or frontend_probe.get("failure_reason")
    )
    return {
        "attempt_count": 1,
        "passed": (
            bool(backend_probe.get("passed"))
            and bool(chatbot_probe.get("passed"))
            and bool(frontend_probe.get("passed"))
        ),
        "failure_reason": failure_reason,
        "backend": backend_probe,
        "chatbot": chatbot_probe,
        "frontend": frontend_probe,
    }


def _run_server_probes_with_live_processes(
    context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, subprocess.Popen[str]]]:
    probe_payload: dict[str, Any] = {
        "attempt_count": 1,
        "passed": False,
        "failure_reason": None,
    }
    live_processes: dict[str, subprocess.Popen[str]] = {}

    for probe_name, plan_key in (("backend", "backend_plan"), ("chatbot", "chatbot_plan"), ("frontend", "frontend_plan")):
        probe = _run_single_server_probe(
            plan=context[plan_key],
            probe_name=probe_name,
            keep_running=True,
        )
        process = probe.pop("process", None)
        probe_payload[probe_name] = probe
        if process is not None:
            live_processes[probe_name] = process
        if not probe.get("passed"):
            probe_payload["failure_reason"] = probe.get("failure_reason")
            _finalize_live_server_probe_outputs(
                probe_payload=probe_payload,
                live_processes=live_processes,
            )
            return probe_payload, {}

    probe_payload["passed"] = True
    return probe_payload, live_processes


def _finalize_live_server_probe_outputs(
    *,
    probe_payload: dict[str, Any],
    live_processes: dict[str, subprocess.Popen[str]],
) -> None:
    for probe_name in ("backend", "chatbot", "frontend"):
        probe = probe_payload.get(probe_name)
        process = live_processes.get(probe_name)
        if not isinstance(probe, dict) or process is None:
            continue
        _terminate_process(process)
        stdout, stderr = _collect_process_output(process)
        probe["stdout"] = stdout
        probe["stderr"] = stderr
        probe["pid"] = getattr(process, "pid", None)


def _run_runtime_contract_probe(
    *,
    run_root: Path,
    site: str,
    backend_base_url: str = "http://127.0.0.1:8000",
    chatbot_base_url: str = "http://127.0.0.1:8100",
) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return _build_skipped_contract_probe("manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _build_skipped_contract_probe("manifest_invalid")
    credentials = manifest.get("credentials") or {}
    auth = (manifest.get("analysis") or {}).get("auth") or {}
    login_route = auth.get("login_route")
    if not credentials or not login_route:
        return _build_skipped_contract_probe("credentials_missing")

    return _run_authenticated_chat_contract_probe(
        site=site,
        credentials=credentials,
        auth=auth,
        backend_base_url=backend_base_url,
        chatbot_base_url=chatbot_base_url,
    )


def _run_single_server_probe(
    *,
    plan: dict[str, Any],
    probe_name: str,
    keep_running: bool = False,
) -> dict[str, Any]:
    command = plan.get("command")
    readiness_url = str(plan.get("readiness_url") or "")
    readiness_method = str(plan.get("readiness_method") or "GET").upper()
    readiness_expected_statuses = {
        int(status)
        for status in (plan.get("readiness_expected_statuses") or [200])
    }
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
            "process": None,
        }

    try:
        process = _launch_server_process(
            command=list(command),
            cwd=working_directory,
            env=dict(plan.get("environment") or {}),
        )
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
            "process": None,
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
            "process": None,
        }

    readiness = _probe_http_ready(
        readiness_url,
        method=readiness_method,
        accepted_statuses=readiness_expected_statuses,
        timeout_seconds=int(plan.get("readiness_timeout_seconds") or 2),
        attempts=int(plan.get("readiness_attempts") or 10),
        delay_seconds=float(plan.get("readiness_delay_seconds") or 0.2),
    )
    if not readiness.get("passed"):
        _terminate_process(process)
        stdout, stderr = _collect_process_output(process)
        return {
            "plan": plan,
            "passed": False,
            "status": "readiness_failed",
            "failure_reason": f"{probe_name}_readiness_failed",
            "stdout": stdout,
            "stderr": stderr,
            "pid": getattr(process, "pid", None),
            "readiness": readiness,
            "process": None,
        }
    if keep_running:
        return {
            "plan": plan,
            "passed": True,
            "status": "ready",
            "failure_reason": None,
            "stdout": "",
            "stderr": "",
            "pid": getattr(process, "pid", None),
            "readiness": readiness,
            "process": process,
        }
    _terminate_process(process)
    stdout, stderr = _collect_process_output(process)
    return {
        "plan": plan,
        "passed": True,
        "status": "ready",
        "failure_reason": None,
        "stdout": stdout,
        "stderr": stderr,
        "pid": getattr(process, "pid", None),
        "readiness": readiness,
        "process": None,
    }


def _run_authenticated_chat_contract_probe(
    *,
    site: str,
    credentials: dict[str, Any] | None = None,
    auth: dict[str, Any] | None = None,
    http_request: Callable[..., dict[str, Any]] | None = None,
    backend_base_url: str = "http://127.0.0.1:8000",
    chatbot_base_url: str = "http://127.0.0.1:8100",
) -> dict[str, Any]:
    auth = auth or {}
    request_fn = http_request or _perform_http_request
    cookie_header = ""
    if credentials and auth.get("login_route"):
        login_fields = [str(field) for field in (auth.get("login_fields") or ["email", "password"]) if str(field)]
        login_body = {field: credentials.get(field, "") for field in login_fields}
        login_route = str(auth.get("login_route") or "/api/users/login/")
        login_response = request_fn(
            method="POST",
            url=f"{backend_base_url}{login_route}",
            headers={"Content-Type": "application/json"},
            body=json.dumps(login_body),
            timeout_seconds=10,
        )
        cookie_header = str(
            (login_response.get("headers") or {}).get("Set-Cookie")
            or (login_response.get("headers") or {}).get("set-cookie")
            or ""
        )
    chat_auth_response = request_fn(
        method="POST",
        url=f"{backend_base_url}/api/chat/auth-token",
        headers={"Cookie": cookie_header} if cookie_header else {},
        timeout_seconds=8,
    )
    chat_auth_body = _parse_json_body(chat_auth_response.get("body"))
    if int(chat_auth_response.get("status") or 0) != 200 or not isinstance(chat_auth_body, dict):
        return {
            "status": "failed",
            "passed": False,
            "failure_reason": "chat_auth_contract_failed",
            "chat_auth": {
                "status": chat_auth_response.get("status"),
                "headers": chat_auth_response.get("headers") or {},
                "body": chat_auth_response.get("body") or "",
                "exports": {},
            },
            "chatbot_stream": None,
        }
    if not chat_auth_body.get("authenticated") or not chat_auth_body.get("access_token"):
        return {
            "status": "failed",
            "passed": False,
            "failure_reason": "chat_auth_contract_failed",
            "chat_auth": {
                "status": chat_auth_response.get("status"),
                "headers": chat_auth_response.get("headers") or {},
                "body": chat_auth_response.get("body") or "",
                "exports": {},
            },
            "chatbot_stream": None,
        }

    shared_assets = resolve_shared_chatbot_assets(site)
    access_token = str(chat_auth_body.get("access_token") or "")
    stream_payload = {
        "message": "테스트 메시지",
        "site_id": shared_assets.site_id,
        "access_token": access_token,
        "previous_state": None,
    }
    stream_response = request_fn(
        method="POST",
        url=f"{chatbot_base_url}/api/v1/chat/stream",
        headers={"Content-Type": "application/json"},
        body=json.dumps(stream_payload, ensure_ascii=False),
        timeout_seconds=10,
    )
    stream_body = str(stream_response.get("body") or "")
    stream_passed = int(stream_response.get("status") or 0) == 200 and (
        "data:" in stream_body or stream_body.strip() != ""
    )
    return {
        "status": "passed" if stream_passed else "failed",
        "passed": stream_passed,
        "failure_reason": None if stream_passed else "chatbot_stream_contract_failed",
        "chat_auth": {
            "status": chat_auth_response.get("status"),
            "headers": chat_auth_response.get("headers") or {},
            "body": chat_auth_response.get("body") or "",
            "exports": {"chat_auth.access_token": access_token},
        },
        "chatbot_stream": {
            "status": stream_response.get("status"),
            "headers": stream_response.get("headers") or {},
            "body": stream_body,
            "request_body": stream_payload,
        },
    }


def _launch_server_process(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    stdout_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    stderr_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    return subprocess.Popen(
        command,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        stdout=stdout_log,
        stderr=stderr_log,
        text=True,
        start_new_session=True,
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    pid = getattr(process, "pid", None)
    used_process_group = False
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, signal.SIGTERM)
            used_process_group = True
        except (ProcessLookupError, PermissionError):
            used_process_group = False
    if not used_process_group:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if isinstance(pid, int) and pid > 0:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        else:
            process.kill()
        process.wait(timeout=2)


def _collect_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    stdout_handle = getattr(process, "stdout", None)
    stderr_handle = getattr(process, "stderr", None)
    stdout = ""
    stderr = ""

    if hasattr(stdout_handle, "seek") and hasattr(stdout_handle, "read"):
        stdout_handle.flush()
        stdout_handle.seek(0)
        stdout = stdout_handle.read() or ""
    if hasattr(stderr_handle, "seek") and hasattr(stderr_handle, "read"):
        stderr_handle.flush()
        stderr_handle.seek(0)
        stderr = stderr_handle.read() or ""

    if stdout or stderr or (
        hasattr(stdout_handle, "seek") and hasattr(stderr_handle, "seek")
    ):
        return stdout, stderr

    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        stdout, stderr = process.communicate(timeout=1)
    return stdout or "", stderr or ""


def _probe_http_ready(
    url: str,
    *,
    method: str = "GET",
    accepted_statuses: set[int] | None = None,
    timeout_seconds: int = 2,
    attempts: int = 10,
    delay_seconds: float = 0.2,
) -> dict[str, Any]:
    allowed_statuses = accepted_statuses or {200}
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return {
                    "passed": True,
                    "url": url,
                    "method": method,
                    "status_code": getattr(response, "status", 200),
                    "attempts": attempt,
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            if exc.code in allowed_statuses:
                return {
                    "passed": True,
                    "url": url,
                    "method": method,
                    "status_code": exc.code,
                    "attempts": attempt,
                    "error": None,
                }
            last_error = str(exc.reason or exc)
        except urllib.error.URLError as exc:
            last_error = str(exc.reason or exc)
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = str(exc)
        if attempt < attempts:
            time.sleep(delay_seconds)
    return {
        "passed": False,
        "url": url,
        "method": method,
        "status_code": None,
        "attempts": attempts,
        "error": last_error or "readiness probe failed",
    }


def _perform_http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout_seconds: int = 5,
) -> dict[str, Any]:
    request_data = body.encode("utf-8") if isinstance(body, str) else None
    request = urllib.request.Request(url, data=request_data, method=method.upper())
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return {
                "status": response.getcode(),
                "headers": dict(response.getheaders()),
                "body": response.read().decode("utf-8", errors="ignore"),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "headers": dict(exc.headers),
            "body": exc.read().decode("utf-8", errors="ignore"),
        }


def _parse_json_body(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, str) or not body.strip():
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


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
