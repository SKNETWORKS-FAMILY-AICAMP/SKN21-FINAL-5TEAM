from __future__ import annotations

import py_compile
import re
from pathlib import Path
from typing import Any

from chatbot.src.onboarding.onboarding_ignore import OnboardingIgnoreMatcher

_TEXT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".vue"}
_HOST_CONTRACT_MARKER = "__ORDER_CS_WIDGET_HOST_CONTRACT__"
_WIDGET_USAGE_MARKER = "<order-cs-widget"
_AUTH_BOOTSTRAP_MARKER = "/api/chat/auth-token"
_HELPER_PATH_SEGMENTS = frozenset(
    {
        "chatbot",
        "components",
        "component",
        "widgets",
        "widget",
        "examples",
        "example",
        "stories",
        "__tests__",
        "test",
        "tests",
    }
)
_LIKELY_MOUNT_SUFFIXES = (
    "frontend/src/App.js",
    "frontend/src/App.jsx",
    "frontend/src/App.ts",
    "frontend/src/App.tsx",
    "frontend/src/App.vue",
    "frontend/src/main.js",
    "frontend/src/main.ts",
    "frontend/src/main.jsx",
    "frontend/src/main.tsx",
    "frontend/pages/_app.js",
    "frontend/pages/_app.jsx",
    "frontend/pages/_app.tsx",
    "frontend/app/layout.js",
    "frontend/app/layout.jsx",
    "frontend/app/layout.tsx",
    "frontend/app/page.js",
    "frontend/app/page.jsx",
    "frontend/app/page.tsx",
    "src/App.js",
    "src/App.jsx",
    "src/App.ts",
    "src/App.tsx",
    "src/App.vue",
)


def evaluate_backend_workspace_static(workspace: Path) -> dict[str, Any]:
    ignore_matcher = OnboardingIgnoreMatcher(workspace)
    checked_files: list[str] = []
    failed_files: list[dict[str, str]] = []
    for path in _iter_python_files(workspace, ignore_matcher):
        relative = path.relative_to(workspace).as_posix()
        checked_files.append(relative)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed_files.append({"path": relative, "error": str(exc)})
    framework = _detect_backend_framework(workspace)
    route_wiring = _evaluate_route_wiring(workspace, framework=framework)
    passed = not failed_files and not route_wiring["validation_errors"]
    failure_summary = ""
    if failed_files:
        failure_summary = f"python compile failed for {failed_files[0]['path']}"
    elif route_wiring["validation_errors"]:
        failure_summary = str(route_wiring["validation_errors"][0])
    return {
        "passed": passed,
        "framework": framework,
        "checked_files": checked_files,
        "failed_files": failed_files,
        "route_wiring": route_wiring,
        "failure_summary": failure_summary or "backend evaluation passed",
        "related_files": sorted(set(checked_files) | set(route_wiring.get("files") or [])),
    }


def evaluate_python_workspace_static(workspace: Path) -> dict[str, Any]:
    ignore_matcher = OnboardingIgnoreMatcher(workspace)
    checked_files: list[str] = []
    failed_files: list[dict[str, str]] = []
    for path in _iter_python_files(workspace, ignore_matcher):
        relative = path.relative_to(workspace).as_posix()
        checked_files.append(relative)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed_files.append({"path": relative, "error": str(exc)})
    passed = not failed_files
    failure_summary = (
        f"python compile failed for {failed_files[0]['path']}"
        if failed_files
        else "python workspace evaluation passed"
    )
    return {
        "passed": passed,
        "checked_files": checked_files,
        "failed_files": failed_files,
        "failure_summary": failure_summary,
        "related_files": checked_files,
    }


def evaluate_selected_python_targets(
    workspace: Path,
    targets: list[str] | set[str],
) -> dict[str, Any]:
    checked_files: list[str] = []
    failed_files: list[dict[str, str]] = []
    for relative in sorted({str(target) for target in targets if str(target).endswith(".py")}):
        path = workspace / relative
        checked_files.append(relative)
        if not path.exists():
            failed_files.append({"path": relative, "error": "target missing"})
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed_files.append({"path": relative, "error": str(exc)})
    passed = not failed_files
    failure_summary = (
        f"python compile failed for {failed_files[0]['path']}"
        if failed_files
        else "selected python target evaluation passed"
    )
    return {
        "passed": passed,
        "checked_files": checked_files,
        "failed_files": failed_files,
        "failure_summary": failure_summary,
        "related_files": checked_files,
    }


def evaluate_frontend_workspace_static(workspace: Path) -> dict[str, Any]:
    framework = _detect_frontend_framework(workspace)
    mount_candidates = _find_mount_candidates(workspace)
    mount_path = _resolve_mount_path(workspace, mount_candidates)
    validation_errors = _collect_validation_errors(
        workspace=workspace,
        mount=mount_path,
        framework=framework,
    )
    passed = not validation_errors
    return {
        "passed": passed,
        "framework": framework,
        "mount_candidates": mount_candidates,
        "mount_path": str(mount_path) if mount_path else None,
        "validation_errors": validation_errors,
        "failure_summary": validation_errors[0] if validation_errors else "frontend evaluation passed",
        "related_files": mount_candidates,
    }


def _iter_python_files(root: Path, ignore_matcher: OnboardingIgnoreMatcher):
    for path in sorted(root.rglob("*.py")):
        if not ignore_matcher.includes(path):
            continue
        yield path


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


def _detect_frontend_framework(root: Path) -> str:
    has_vue = any(path.suffix == ".vue" for path, _ in _iter_text_files(root))
    if has_vue:
        return "vue"
    for path, text in _iter_text_files(root):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        if "return <" in text or "React" in text or "function App" in text:
            return "react"
    return "unknown"


def _find_mount_candidates(root: Path) -> list[str]:
    mounts: list[str] = []
    seen: set[str] = set()
    for path, text in _iter_text_files(root):
        if _is_widget_host_artifact(path, text):
            continue
        relative = path.relative_to(root).as_posix()
        if _is_likely_mount_path(relative):
            if relative not in seen:
                mounts.append(relative)
                seen.add(relative)
            continue
        if _is_helper_candidate_path(relative):
            continue
        if any(
            marker in text
            for marker in (
                _HOST_CONTRACT_MARKER,
                _WIDGET_USAGE_MARKER,
                "widgetBundlePath",
                "/widget.js",
                "orderCsWidgetScript",
            )
        ):
            if relative not in seen:
                mounts.append(relative)
                seen.add(relative)
    return mounts


def _iter_text_files(root: Path):
    ignore_matcher = OnboardingIgnoreMatcher(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        if not ignore_matcher.includes(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        yield path, text


def _resolve_mount_path(root: Path, candidates: list[str]) -> Path | None:
    for candidate in candidates:
        candidate_path = root / candidate
        if candidate_path.exists():
            return candidate_path
    return None


def _is_likely_mount_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    return normalized.endswith(_LIKELY_MOUNT_SUFFIXES)


def _is_helper_candidate_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    segments = [segment for segment in normalized.split("/") if segment]
    return any(segment in _HELPER_PATH_SEGMENTS for segment in segments[:-1])


def _collect_validation_errors(
    *,
    workspace: Path,
    mount: Path | None,
    framework: str,
) -> list[str]:
    del workspace
    errors: list[str] = []
    if mount is None:
        errors.append("mount candidate unavailable")
    else:
        if not _has_bundle_bootstrap(mount):
            errors.append("mount missing order-cs-widget bundle bootstrap")
        if not _has_auth_bootstrap_contract(mount):
            errors.append("mount missing auth bootstrap contract")
        if not _has_widget_usage(mount):
            errors.append("mount missing order-cs-widget usage")
        if framework == "react" and _has_routes_child_violation(mount):
            errors.append("routes child violation")
    return errors


def _has_bundle_bootstrap(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return (
        _HOST_CONTRACT_MARKER in content
        and "widgetBundlePath" in content
        and (
            "/widget.js" in content
            or "orderCsWidgetScript.src" in content
            or "data-order-cs-widget-bundle" in content
        )
    )


def _has_auth_bootstrap_contract(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "authBootstrapPath" in content and _AUTH_BOOTSTRAP_MARKER in content


def _has_widget_usage(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return _WIDGET_USAGE_MARKER in content


def _has_routes_child_violation(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    routes_blocks = re.findall(r"<Routes>(.*?)</Routes>", content, flags=re.DOTALL)
    return any(_WIDGET_USAGE_MARKER in block for block in routes_blocks)


def _is_widget_host_artifact(path: Path, text: str) -> bool:
    return (
        "ORDER_CS_WIDGET_HOST_CONTRACT" in text
        and "ensureOrderCsWidgetHost" in text
        and path.as_posix().endswith("orderCsWidgetHost.js")
    )
