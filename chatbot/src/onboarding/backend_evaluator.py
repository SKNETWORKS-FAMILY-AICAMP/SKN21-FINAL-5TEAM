from __future__ import annotations

import json
import py_compile
from pathlib import Path


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
    framework = _detect_backend_framework(workspace)
    entrypoints = _find_entrypoints(workspace, framework)
    entrypoint_smoke: list[dict[str, object]] = []

    for path in sorted(workspace.rglob("*.py")):
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
        "passed": len(failed_files) == 0,
    }
    output_path = reports / "backend-evaluation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _detect_backend_framework(root: Path) -> str:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in root.rglob("*.py")
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
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root).as_posix()
        if framework == "fastapi" and ("FastAPI(" in text or "include_router(" in text):
            entrypoints.append(relative)
        elif framework == "flask" and ("Flask(" in text or "create_app(" in text):
            entrypoints.append(relative)
        elif framework == "django" and "urlpatterns" in text:
            entrypoints.append(relative)
    return entrypoints
