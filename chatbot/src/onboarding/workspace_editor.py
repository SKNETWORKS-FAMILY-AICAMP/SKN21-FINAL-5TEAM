from __future__ import annotations

from pathlib import Path
from typing import Any


SUPPORTED_EDIT_OPERATIONS = {
    "replace_text",
    "insert_after",
    "insert_before",
    "append_text",
}


def apply_direct_edit_operations(*, workspace_root: str | Path, operations: list[dict[str, Any]]) -> dict[str, Any]:
    workspace = Path(workspace_root)
    workspace_resolved = workspace.resolve()
    applied_edits: list[dict[str, str]] = []
    staged_contents: dict[Path, str] = {}

    for operation in operations:
        relative_path = _validate_relative_path(str(operation.get("path") or ""))
        target_path = workspace / relative_path
        operation_name = str(operation.get("operation") or "")
        if operation_name not in SUPPORTED_EDIT_OPERATIONS:
            raise ValueError(f"unsupported operation: {operation_name}")
        if not target_path.exists() or not target_path.is_file():
            raise ValueError(f"target file not found: {relative_path}")
        _validate_target_path(target_path=target_path, workspace_root=workspace_resolved)

        content = staged_contents.get(target_path)
        if content is None:
            content = _read_utf8(target_path)
        updated = _apply_operation(content=content, operation=operation)
        staged_contents[target_path] = updated
        applied_edits.append({"path": relative_path, "operation": operation_name})

    for target_path, updated in staged_contents.items():
        target_path.write_text(updated, encoding="utf-8")

    return {"applied_edits": applied_edits}


def _validate_relative_path(raw_path: str) -> str:
    path = raw_path.strip().replace("\\", "/")
    if not path:
        raise ValueError("path is required")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must be a relative path inside the workspace")
    return candidate.as_posix()


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file must be utf-8 text: {path.as_posix()}") from exc


def _validate_target_path(*, target_path: Path, workspace_root: Path) -> None:
    try:
        target_path.resolve().relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("target file must stay inside the workspace") from exc


def _apply_operation(*, content: str, operation: dict[str, Any]) -> str:
    operation_name = str(operation.get("operation") or "")
    if operation_name == "replace_text":
        old = str(operation.get("old") or "")
        if not old or old not in content:
            raise ValueError("replace_text requires an existing old value")
        return content.replace(old, str(operation.get("new") or ""), 1)
    if operation_name == "insert_after":
        anchor = str(operation.get("anchor") or "")
        if not anchor or anchor not in content:
            raise ValueError("insert_after requires an existing anchor")
        return content.replace(anchor, anchor + str(operation.get("content") or ""), 1)
    if operation_name == "insert_before":
        anchor = str(operation.get("anchor") or "")
        if not anchor or anchor not in content:
            raise ValueError("insert_before requires an existing anchor")
        return content.replace(anchor, str(operation.get("content") or "") + anchor, 1)
    if operation_name == "append_text":
        return content + str(operation.get("content") or "")
    raise ValueError(f"unsupported operation: {operation_name}")
