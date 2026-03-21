from __future__ import annotations

from pathlib import Path
from typing import Any

SHARED_WIDGET_LEGACY_MARKERS = [
    "__ORDER_CS_WIDGET_HOST_CONTRACT__",
    "order-cs-widget",
    "widgetBundlePath",
    "/widget.js",
]


def attempt_frontend_recovery(
    *,
    workspace: Path,
    mount_candidate: Path | None,
    widget_path: Path | None,
    errors: list[str],
) -> dict[str, Any]:
    notes: list[str] = []
    resolved_mount = mount_candidate
    unrecoverable_errors = {
        "routes child violation",
    }

    if any(error in unrecoverable_errors for error in errors):
        notes.append("frontend validation hit unrecoverable guardrail")
        return _hard_fallback(notes, errors)

    if resolved_mount is None:
        resolved_mount = _discover_mount_in_workspace(workspace)
        if resolved_mount:
            notes.append(f"recovered mount candidate via discovery at {resolved_mount}")
        else:
            notes.append("mount candidate missing; cannot recover")
            return _hard_fallback(notes, errors)

    if not _mount_contains_bundle_bootstrap(resolved_mount):
        notes.append("mount candidate missing shared widget bundle bootstrap")
        return _hard_fallback(notes, errors)
    if not _mount_contains_auth_bootstrap_contract(resolved_mount):
        notes.append("mount candidate missing auth bootstrap contract")
        return _hard_fallback(notes, errors)
    if not _mount_contains_widget_usage(resolved_mount):
        notes.append("mount candidate missing order-cs-widget usage")
        return _hard_fallback(notes, errors)

    return _recovered(None, resolved_mount, notes)


def _discover_mount_in_workspace(workspace: Path) -> Path | None:
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if any(marker in content for marker in SHARED_WIDGET_LEGACY_MARKERS):
            return path
    return None


def _mount_contains_bundle_bootstrap(mount: Path) -> bool:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    return (
        "__ORDER_CS_WIDGET_HOST_CONTRACT__" in content
        and "widgetBundlePath" in content
        and ("/widget.js" in content or "orderCsWidgetScript.src" in content)
    )


def _mount_contains_auth_bootstrap_contract(mount: Path) -> bool:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    return "authBootstrapPath" in content and "/api/chat/auth-token" in content


def _mount_contains_widget_usage(mount: Path) -> bool:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    return "<order-cs-widget" in content


def _mount_contains_widget_reference(mount: Path) -> bool:
    content = mount.read_text(encoding="utf-8", errors="ignore")
    return any(marker in content for marker in SHARED_WIDGET_LEGACY_MARKERS)


def _recovered(widget: Path | None, mount: Path, notes: list[str]) -> dict[str, Any]:
    return {
        "status": "recovered",
        "notes": notes,
        "widget_path": str(widget) if widget else None,
        "mount_path": str(mount),
    }


def _hard_fallback(notes: list[str], errors: list[str]) -> dict[str, Any]:
    return {
        "status": "hard_fallback",
        "notes": notes + ["errors: " + "; ".join(errors)],
        "widget_path": None,
        "mount_path": None,
    }
