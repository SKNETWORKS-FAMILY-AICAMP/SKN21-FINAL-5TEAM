from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .debug_logging import append_onboarding_event
from .onboarding_ignore import OnboardingIgnoreMatcher

try:
    from .frontend_build_runner import run_frontend_build
    from .frontend_build_runner import classify_frontend_bootstrap_result
except ImportError:
    run_frontend_build = None
    classify_frontend_bootstrap_result = None

from .frontend_recovery import attempt_frontend_recovery

TEXT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".vue"}


def evaluate_frontend_workspace(
    *,
    runtime_workspace: str | Path,
    report_root: str | Path,
) -> Path:
    workspace = Path(runtime_workspace)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    run_id = workspace.parent.name if workspace.parent.name else "unknown"

    append_onboarding_event(
        report_root=reports,
        run_id=run_id,
        component="frontend_evaluator",
        stage="validation",
        event="stage_started",
        severity="info",
        summary="frontend evaluation started",
        source="system",
        details={"workspace_root": str(workspace)},
    )

    framework = _detect_frontend_framework(workspace)
    mount_candidates = _find_mount_candidates(workspace)
    widget_file = _find_widget_file(workspace)
    widget_path: Path | None = widget_file
    mount_path = _resolve_mount_path(workspace, mount_candidates)
    frontend_root = _resolve_frontend_root(workspace)
    validation_errors = _collect_validation_errors(
        workspace=workspace,
        widget=widget_file,
        mount=mount_path,
        framework=framework,
    )
    validation_status = "valid" if not validation_errors else "invalid"
    source = "llm"
    recovery_notes: list[str] = []

    if validation_errors:
        recovery = attempt_frontend_recovery(
            workspace=workspace,
            mount_candidate=mount_path,
            widget_path=widget_file,
            errors=validation_errors,
        )
        if recovery.get("status") == "recovered":
            source = "recovered_llm"
            widget_path = (
                Path(recovery["widget_path"])
                if recovery.get("widget_path")
                else widget_path
            )
            mount_path = (
                Path(recovery["mount_path"])
                if recovery.get("mount_path")
                else mount_path
            )
            recovery_notes = recovery.get("notes", [])
            append_onboarding_event(
                report_root=reports,
                run_id=run_id,
                component="frontend_evaluator",
                stage="validation",
                event="recovery_applied",
                severity="info",
                summary="frontend recovery applied",
                source=source,
                recovery={"applied": True, "reason": "frontend_validation_recovery"},
                details={"validation_errors": validation_errors, "notes": recovery_notes},
            )
        else:
            source = "hard_fallback"
            recovery_notes = recovery.get("notes", [])
            append_onboarding_event(
                report_root=reports,
                run_id=run_id,
                component="frontend_evaluator",
                stage="validation",
                event="hard_fallback_used",
                severity="warn",
                summary="frontend hard fallback used",
                source=source,
                recovery={"applied": False, "reason": "frontend_validation_failed"},
                details={"validation_errors": validation_errors, "notes": recovery_notes},
            )

    build_validation = _build_frontend_build_validation(
        frontend_root=frontend_root,
        mount_path=mount_path,
        widget_path=widget_path,
        framework=framework,
    )
    if build_validation["bootstrap_failure_stage"] and source == "llm":
        source = "hard_fallback"
        recovery_notes = [*recovery_notes, "frontend bootstrap failed after artifact validation"]
        recovery_reason = (
            "frontend_install_failed"
            if build_validation["bootstrap_failure_stage"] == "install_environment_failed"
            else "frontend_build_failed"
        )
        append_onboarding_event(
            report_root=reports,
            run_id=run_id,
            component="frontend_evaluator",
            stage="validation",
            event="hard_fallback_used",
            severity="warn",
            summary="frontend bootstrap failed and used hard fallback",
            source=source,
            recovery={"applied": False, "reason": recovery_reason},
            details={
                "failure_reason": build_validation["bootstrap_failure_reason"],
                "failure_stage": build_validation["bootstrap_failure_stage"],
            },
        )

    artifact = {
        "widget_path": str(widget_path) if widget_path else None,
        "mount_path": str(mount_path) if mount_path else None,
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "source": source,
        "recovery_notes": recovery_notes,
    }

    payload = {
        "workspace_root": str(workspace),
        "framework": framework,
        "mount_candidates": mount_candidates,
        "passed": (
            validation_status == "valid"
            and (
                build_validation["bootstrap_passed"]
                or (not build_validation["install_attempted"] and not build_validation["build_attempted"])
            )
        ),
        "package_manager": build_validation["package_manager"],
        "install_attempted": build_validation["install_attempted"],
        "install_passed": build_validation["install_passed"],
        "install_command": build_validation["install_command"],
        "build_attempted": build_validation["build_attempted"],
        "build_skipped": build_validation["build_skipped"],
        "build_command": build_validation["build_command"],
        "build_passed": build_validation["build_passed"],
        "bootstrap_passed": build_validation["bootstrap_passed"],
        "bootstrap_failure_stage": build_validation["bootstrap_failure_stage"],
        "bootstrap_failure_reason": build_validation["bootstrap_failure_reason"],
        "runtime_checks": build_validation["runtime_checks"],
        "failure_reason": build_validation["failure_reason"],
        "frontend_artifact": artifact,
    }
    output_path = reports / "frontend-evaluation.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (reports / "frontend-build-validation.json").write_text(
        json.dumps(
            {
                **build_validation,
                "source": source,
                "validation_errors": validation_errors,
                "recovery_notes": recovery_notes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    append_onboarding_event(
        report_root=reports,
        run_id=run_id,
        component="frontend_evaluator",
        stage="validation",
        event="stage_completed",
        severity="info" if source != "hard_fallback" else "warn",
        summary="frontend evaluation completed",
        source=source,
        details={
            "validation_status": validation_status,
            "build_passed": build_validation["build_passed"],
            "report_path": str(output_path),
        },
    )
    return output_path


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
    for path, text in _iter_text_files(root):
        if "SharedChatbotWidget" in path.name:
            continue
        if "Chatbot" in text or "ChatBot" in text:
            mounts.append(path.relative_to(root).as_posix())
    return mounts


def _iter_text_files(root: Path):
    ignore_matcher = OnboardingIgnoreMatcher(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if not ignore_matcher.includes(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        yield path, text


def _find_widget_file(root: Path) -> Path | None:
    for path in root.rglob("*SharedChatbotWidget*"):
        if path.is_file():
            return path
    return None


def _resolve_frontend_root(root: Path) -> Path:
    frontend_root = root / "frontend"
    if frontend_root.exists():
        return frontend_root
    return root


def _resolve_mount_path(root: Path, candidates: list[str]) -> Path | None:
    for candidate in candidates:
        candidate_path = root / candidate
        if candidate_path.exists():
            return candidate_path
    return None


def _collect_validation_errors(
    *,
    workspace: Path,
    widget: Path | None,
    mount: Path | None,
    framework: str,
) -> list[str]:
    errors: list[str] = []
    if widget is None:
        errors.append("widget file not found")
    elif not _is_widget_path_allowed(workspace=workspace, widget=widget):
        errors.append("widget path outside frontend/src")
    if mount is None:
        errors.append("mount candidate unavailable")
    else:
        if mount.suffix.lower() != ".vue" and not _has_import(mount):
            errors.append("mount missing SharedChatbotWidget import")
        import_target = _resolve_widget_import_target(mount)
        if _has_import(mount) and (import_target is None or not import_target.exists()):
            errors.append("missing import target")
        if not _has_widget_usage(mount):
            errors.append("mount missing SharedChatbotWidget usage")
        if framework == "react" and _has_routes_child_violation(mount):
            errors.append("routes child violation")
    return errors


def _has_import(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "import SharedChatbotWidget" in content


def _has_widget_usage(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "<SharedChatbotWidget" in content or "SharedChatbotWidget />" in content


def _is_widget_path_allowed(*, workspace: Path, widget: Path) -> bool:
    frontend_src = workspace / "frontend" / "src"
    try:
        widget.relative_to(frontend_src)
        return True
    except ValueError:
        return False


def _resolve_widget_import_target(mount: Path) -> Path | None:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    match = re.search(
        r'import\s+SharedChatbotWidget\s+from\s+[\'"]([^\'"]+)[\'"]',
        content,
    )
    if match is None:
        return None
    raw_target = match.group(1).strip()
    candidate = (mount.parent / raw_target).resolve()
    if candidate.suffix:
        return candidate
    for suffix in (".js", ".jsx", ".ts", ".tsx", ".vue"):
        if candidate.with_suffix(suffix).exists():
            return candidate.with_suffix(suffix)
    return candidate


def _has_routes_child_violation(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    routes_blocks = re.findall(r"<Routes>(.*?)</Routes>", content, flags=re.DOTALL)
    return any("<SharedChatbotWidget" in block for block in routes_blocks)


def _build_frontend_build_validation(
    *,
    frontend_root: Path,
    mount_path: Path | None,
    widget_path: Path | None,
    framework: str,
) -> dict[str, Any]:
    action_result: dict[str, Any] = {}
    package_manager = None
    if run_frontend_build is not None and (frontend_root / "package.json").exists():
        action_result = run_frontend_build(workspace=frontend_root, timeout=120) or {}
        package_manager = action_result.get("package_manager")

    install_result = action_result.get("install_result") if isinstance(action_result, dict) else None
    build_result = action_result.get("build_result") if isinstance(action_result, dict) else None
    bootstrap_summary = (
        classify_frontend_bootstrap_result(
            install_result=install_result if isinstance(install_result, dict) else None,
            build_result=build_result if isinstance(build_result, dict) else None,
        )
        if classify_frontend_bootstrap_result is not None
        else {
            "install_attempted": isinstance(install_result, dict),
            "install_passed": False,
            "build_attempted": isinstance(build_result, dict),
            "build_passed": False,
            "bootstrap_passed": False,
            "bootstrap_failure_stage": None,
            "bootstrap_failure_reason": None,
        }
    )
    install_attempted = bootstrap_summary["install_attempted"]
    install_passed = bootstrap_summary["install_passed"]
    build_attempted = bootstrap_summary["build_attempted"]
    build_passed = bootstrap_summary["build_passed"]
    bootstrap_passed = bootstrap_summary["bootstrap_passed"]
    bootstrap_failure_stage = bootstrap_summary["bootstrap_failure_stage"]
    bootstrap_failure_reason = bootstrap_summary["bootstrap_failure_reason"]
    runtime_checks = _evaluate_runtime_checks(
        frontend_root=frontend_root,
        mount_path=mount_path,
        widget_path=widget_path,
        framework=framework,
    )
    if (
        build_attempted
        and not build_passed
        and runtime_checks["build_artifact_exists"]
        and _is_warning_only_output(bootstrap_failure_reason)
    ):
        build_passed = True
        bootstrap_passed = bool(install_passed)
        bootstrap_failure_stage = None
        bootstrap_failure_reason = None
    failure_reason = bootstrap_failure_reason

    return {
        "package_manager": package_manager,
        "install_attempted": install_attempted,
        "install_passed": install_passed,
        "install_command": install_result.get("command") if install_attempted else None,
        "build_attempted": build_attempted,
        "build_skipped": bool(action_result.get("build_skipped")) if isinstance(action_result, dict) else False,
        "build_command": build_result.get("command") if build_attempted else None,
        "build_passed": build_passed,
        "bootstrap_passed": bootstrap_passed,
        "bootstrap_failure_stage": bootstrap_failure_stage,
        "bootstrap_failure_reason": bootstrap_failure_reason,
        "runtime_checks": runtime_checks,
        "failure_reason": failure_reason,
    }


def _is_warning_only_output(text: str | None) -> bool:
    if not text:
        return False
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return False
    return all("warning" in line.lower() or "trace-deprecation" in line.lower() for line in lines)


def _evaluate_runtime_checks(
    *,
    frontend_root: Path,
    mount_path: Path | None,
    widget_path: Path | None,
    framework: str,
) -> dict[str, bool]:
    return {
        "mount_exists": bool(mount_path and mount_path.exists()),
        "widget_exists": bool(widget_path and widget_path.exists()),
        "import_present": bool(mount_path and (mount_path.suffix.lower() == ".vue" or _has_import(mount_path))),
        "widget_usage_present": bool(mount_path and _has_widget_usage(mount_path)),
        "bootstrap_auth_fetch_present": bool(widget_path and _has_bootstrap_auth_fetch(widget_path)),
        "build_artifact_exists": _build_artifact_exists(frontend_root=frontend_root, framework=framework),
    }


def _build_artifact_exists(*, frontend_root: Path, framework: str) -> bool:
    candidates: list[Path] = []
    if framework in {"react", "vue", "unknown"}:
        candidates.extend([frontend_root / "dist", frontend_root / "build"])
    if framework == "next":
        candidates.append(frontend_root / ".next")
    return any(path.exists() for path in candidates)


def _has_bootstrap_auth_fetch(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "/api/chat/auth-token" in content and "fetch(" in content
