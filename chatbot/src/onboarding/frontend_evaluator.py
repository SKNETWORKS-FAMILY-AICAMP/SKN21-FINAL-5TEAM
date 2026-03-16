from __future__ import annotations

import json
from pathlib import Path


TEXT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".vue"}


def evaluate_frontend_workspace(
    *,
    runtime_workspace: str | Path,
    report_root: str | Path,
) -> Path:
    workspace = Path(runtime_workspace)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)

    framework = _detect_frontend_framework(workspace)
    mount_candidates = _find_mount_candidates(workspace)
    payload = {
        "workspace_root": str(workspace),
        "framework": framework,
        "mount_candidates": mount_candidates,
        "passed": len(mount_candidates) > 0 or framework == "unknown",
    }
    output_path = reports / "frontend-evaluation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _detect_frontend_framework(root: Path) -> str:
    has_vue = any(path.suffix == ".vue" for path in root.rglob("*.vue"))
    if has_vue:
        return "vue"

    for path in root.rglob("*"):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "return <" in text or "React" in text or "function App" in text:
            return "react"
    return "unknown"


def _find_mount_candidates(root: Path) -> list[str]:
    mounts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Chatbot" in text or "ChatBot" in text:
            mounts.append(path.relative_to(root).as_posix())
    return mounts
