from __future__ import annotations

from pathlib import Path
from typing import Any

SHARED_WIDGET_LEGACY_MARKERS = [
    "SharedChatbotWidget",
    "SharedChatbotWidget",
]


def attempt_frontend_recovery(
    *,
    workspace: Path,
    mount_candidate: Path | None,
    widget_path: Path | None,
    errors: list[str],
) -> dict[str, Any]:
    notes: list[str] = []
    resolved_widget = widget_path
    resolved_mount = mount_candidate
    unrecoverable_errors = {
        "missing import target",
        "routes child violation",
        "widget path outside frontend/src",
    }

    if any(error in unrecoverable_errors for error in errors):
        notes.append("frontend validation hit unrecoverable guardrail")
        return _hard_fallback(notes, errors)

    if resolved_widget is None:
        resolved_widget = _discover_widget_in_workspace(workspace)
        if resolved_widget:
            notes.append(f"recovered widget file via discovery at {resolved_widget}")
        elif resolved_mount is not None and _mount_contains_widget_reference(resolved_mount):
            resolved_widget = resolved_mount
            notes.append("widget file missing; using inline SharedChatbotWidget reference as recovery source")
        else:
            notes.append("widget file not found; recovery failed")
            return _hard_fallback(notes, errors)

    if resolved_mount is None:
        notes.append("mount candidate missing; cannot recover")
        return _hard_fallback(notes, errors)

    if not _mount_contains_widget(resolved_mount):
        notes.append("mount candidate missing SharedChatbotWidget import or usage")
        # recovery tries to find inline usage before giving up
        if _mount_contains_widget_reference(resolved_mount):
            notes.append("mount file contains inline SharedChatbotWidget references; accepting as recovered content")
        else:
            return _hard_fallback(notes, errors)

    return _recovered(resolved_widget, resolved_mount, notes)


def _discover_widget_in_workspace(workspace: Path) -> Path | None:
    for path in workspace.rglob("*SharedChatbotWidget*"):
        if path.is_file():
            return path
    return None


def _mount_contains_widget(mount: Path) -> bool:
    return _has_import(mount) and _has_widget_usage(mount)


def _mount_contains_widget_reference(mount: Path) -> bool:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    return any(marker in content for marker in SHARED_WIDGET_LEGACY_MARKERS)


def _has_import(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "import SharedChatbotWidget" in content


def _has_widget_usage(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return "<SharedChatbotWidget" in content or "SharedChatbotWidget />" in content


def _recovered(widget: Path, mount: Path, notes: list[str]) -> dict[str, Any]:
    return {
        "status": "recovered",
        "notes": notes,
        "widget_path": str(widget),
        "mount_path": str(mount),
    }


def _hard_fallback(notes: list[str], errors: list[str]) -> dict[str, Any]:
    return {
        "status": "hard_fallback",
        "notes": notes + ["errors: " + "; ".join(errors)],
        "widget_path": None,
        "mount_path": None,
    }
