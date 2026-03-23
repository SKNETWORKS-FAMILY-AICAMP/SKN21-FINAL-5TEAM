from __future__ import annotations

import json
import py_compile
from pathlib import Path

from .backend_build_runner import build_plan_for_workspace, run_backend_bootstrap
from .onboarding_ignore import OnboardingIgnoreMatcher


def evaluate_backend_workspace(
    *,
    runtime_workspace: str | Path,
    report_root: str | Path,
) -> Path:
    workspace = Path(runtime_workspace)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)

    checked_files: list[str] = []
    failed_files: list[dict[str, str]] = []
    ignore_matcher = OnboardingIgnoreMatcher(workspace)
    framework = _detect_backend_framework(workspace)
    entrypoints = _find_entrypoints(workspace, framework)
    entrypoint_smoke: list[dict[str, object]] = []
    route_wiring = _evaluate_route_wiring(workspace, framework=framework)
    tool_registry = _evaluate_tool_registry(workspace)
    backend_root = _resolve_backend_root(workspace)
    bootstrap_plan = build_plan_for_workspace(backend_root)
    bootstrap_payload = _build_backend_bootstrap_payload(
        backend_root=backend_root,
        bootstrap_plan=bootstrap_plan,
    )

    for path in _iter_python_files(workspace, ignore_matcher):
        relative = path.relative_to(workspace).as_posix()
        checked_files.append(relative)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed_files.append({"path": relative, "error": str(exc)})

    for relative in entrypoints:
        path = workspace / relative
        ok = True
        error = ""
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            ok = False
            error = str(exc)
        entrypoint_smoke.append(
            {
                "path": relative,
                "ok": ok,
                "error": error,
            }
        )

    payload = {
        "workspace_root": str(workspace),
        "checked_files": checked_files,
        "failed_files": failed_files,
        "framework": framework,
        "entrypoint_smoke": entrypoint_smoke,
        "route_wiring": route_wiring,
        "tool_registry": tool_registry,
        "backend_bootstrap": bootstrap_payload,
        "passed": len(failed_files) == 0 and not route_wiring["validation_errors"],
    }
    output_path = reports / "backend-evaluation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _detect_backend_framework(root: Path) -> str:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in _iter_python_files(root, OnboardingIgnoreMatcher(root))
    )
    if "from fastapi import" in combined or "FastAPI(" in combined or "APIRouter(" in combined:
        return "fastapi"
    if "from flask import" in combined or "Flask(" in combined or "Blueprint(" in combined:
        return "flask"
    if "from django." in combined or "urlpatterns" in combined or "path(" in combined:
        return "django"
    return "unknown"


def _find_entrypoints(root: Path, framework: str) -> list[str]:
    entrypoints: list[str] = []
    for path in _iter_python_files(root, OnboardingIgnoreMatcher(root)):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root).as_posix()
        if framework == "fastapi" and ("FastAPI(" in text or "include_router(" in text):
            entrypoints.append(relative)
        elif framework == "flask" and ("Flask(" in text or "create_app(" in text):
            entrypoints.append(relative)
        elif framework == "django" and "urlpatterns" in text:
            entrypoints.append(relative)
    return entrypoints


def _evaluate_route_wiring(root: Path, *, framework: str) -> dict[str, object]:
    detected_files: list[str] = []
    validation_errors: list[str] = []
    for path in _iter_python_files(root, OnboardingIgnoreMatcher(root)):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/chat/auth-token" in text or "api/chat/auth-token" in text:
            detected_files.append(path.relative_to(root).as_posix())
    registration_points = _find_route_registration_points(root, framework=framework)
    detected_registration_point = _choose_registration_point(registration_points)
    chat_auth_target = _resolve_chat_auth_target(root)
    if detected_files and chat_auth_target is None:
        validation_errors.append("missing chat auth import target")
    if detected_files and detected_registration_point:
        if any(path != detected_registration_point for path in detected_files):
            validation_errors.append("route target outside detected registration point")
    return {
        "chat_auth_route_detected": bool(detected_files),
        "files": detected_files,
        "registration_points": registration_points,
        "detected_registration_point": detected_registration_point,
        "chat_auth_import_target": str(chat_auth_target.relative_to(root)) if chat_auth_target else None,
        "validation_errors": validation_errors,
    }


def _iter_python_files(root: Path, ignore_matcher: OnboardingIgnoreMatcher):
    for path in sorted(root.rglob("*.py")):
        if not ignore_matcher.includes(path):
            continue
        yield path


def _evaluate_tool_registry(root: Path) -> dict[str, object]:
    registry_path = root / "backend" / "tool_registry.py"
    if not registry_path.exists():
        return {
            "exists": False,
            "enabled_tools": [],
        }
    content = registry_path.read_text(encoding="utf-8", errors="ignore")
    enabled_tools = sorted(
        {
            tool
            for tool in [
                "product_list",
                "product_get",
                "orders_list",
                "orders_get",
                "orders_action",
                "list_orders",
                "get_order_status",
                "cancel",
                "refund",
                "exchange",
            ]
            if f'"{tool}"' in content or f"'{tool}'" in content
        }
    )
    return {
        "exists": True,
        "enabled_tools": enabled_tools,
    }


def _find_route_registration_points(root: Path, *, framework: str) -> list[str]:
    points: list[str] = []
    for path in _iter_python_files(root, OnboardingIgnoreMatcher(root)):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root).as_posix()
        if framework == "django" and "urlpatterns" in text:
            points.append(relative)
        elif framework == "flask" and "register_blueprint(" in text:
            points.append(relative)
        elif framework == "fastapi" and ("include_router(" in text or "FastAPI(" in text):
            points.append(relative)
    return sorted(dict.fromkeys(points))


def _choose_registration_point(registration_points: list[str]) -> str | None:
    if not registration_points:
        return None
    def score(item: str) -> tuple[int, int, int, str]:
        priority = 1
        lowered = item.lower()
        if lowered.endswith(("foodshop/urls.py", "config/urls.py", "project/urls.py", "app.py", "main.py")):
            priority = 0
        return (priority, len(Path(item).parts), len(item), item)

    return sorted(registration_points, key=score)[0]


def _resolve_chat_auth_target(root: Path) -> Path | None:
    for candidate in [root / "backend" / "chat_auth.py", root / "chat_auth.py"]:
        if candidate.exists():
            return candidate
    return None


def _resolve_backend_root(root: Path) -> Path:
    backend_root = root / "backend"
    if backend_root.exists():
        return backend_root
    return root


def _build_backend_bootstrap_payload(
    *,
    backend_root: Path,
    bootstrap_plan,
) -> dict[str, object]:
    if bootstrap_plan.manifest_source is None:
        return {
            "bootstrap_attempted": False,
            "bootstrap_source": None,
            "venv_path": str(backend_root / bootstrap_plan.venv_dir),
            "create_venv_command": None,
            "install_command": None,
            "bootstrap_passed": False,
            "bootstrap_failure_reason": "no backend dependency manifest found",
        }

    action_result = run_backend_bootstrap(workspace=backend_root, timeout=120)
    create_venv_result = action_result.get("create_venv_result")
    install_result = action_result.get("install_result")
    create_ok = not isinstance(create_venv_result, dict) or (
        create_venv_result.get("returncode") == 0 and create_venv_result.get("timed_out") is False
    )
    install_ok = not isinstance(install_result, dict) or (
        install_result.get("returncode") == 0 and install_result.get("timed_out") is False
    )
    failure_reason = None
    if not create_ok and isinstance(create_venv_result, dict):
        failure_reason = str(create_venv_result.get("stderr") or create_venv_result.get("stdout") or "backend venv creation failed").strip()
    elif not install_ok and isinstance(install_result, dict):
        failure_reason = str(install_result.get("stderr") or install_result.get("stdout") or "backend dependency install failed").strip()

    return {
        "bootstrap_attempted": True,
        "bootstrap_source": bootstrap_plan.manifest_source,
        "venv_path": action_result.get("venv_path") or str(backend_root / bootstrap_plan.venv_dir),
        "create_venv_command": create_venv_result.get("command") if isinstance(create_venv_result, dict) else bootstrap_plan.create_venv_command,
        "install_command": install_result.get("command") if isinstance(install_result, dict) else bootstrap_plan.install_command,
        "bootstrap_passed": create_ok and install_ok,
        "bootstrap_failure_reason": failure_reason,
    }
