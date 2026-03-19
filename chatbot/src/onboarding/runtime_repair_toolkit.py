from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


def resolve_python_module_candidates(*, workspace_root: str | Path, module_name: str) -> list[Path]:
    workspace = Path(workspace_root)
    normalized_module = module_name.strip().strip(".")
    if not normalized_module:
        return []

    candidates: list[tuple[int, Path]] = []
    seen: set[Path] = set()

    for path in workspace.rglob("*.py"):
        module_path = _module_path_for_file(workspace, path)
        if module_path is None:
            continue
        if not _module_matches(module_path, normalized_module):
            continue
        score = 0 if module_path == normalized_module else 1
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append((score, path))

    candidates.sort(key=lambda item: (item[0], len(item[1].parts), str(item[1])))
    return [path for _, path in candidates]


def choose_runtime_import_replacement(
    *,
    workspace_root: str | Path,
    caller_file: str | Path,
    broken_import: str,
) -> str | None:
    workspace = Path(workspace_root)
    caller = Path(caller_file)
    candidates = resolve_python_module_candidates(workspace_root=workspace, module_name=broken_import)
    if not candidates:
        return None

    target = candidates[0]
    target_module = _module_path_for_file(workspace, target)
    if target_module is None:
        return None

    caller_module = _module_path_for_file(workspace, caller)
    if caller_module is not None:
        caller_root = caller_module.split(".", 1)[0]
        target_root = target_module.split(".", 1)[0]
        if caller_root == target_root == broken_import.split(".", 1)[0]:
            return target_module.split(".", 1)[1] if "." in target_module else target_module

    return target_module


def rewrite_python_import_line(
    *,
    file_path: str | Path,
    broken_import: str,
    replacement_import: str,
) -> bool:
    path = Path(file_path)
    original_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten_lines: list[str] = []
    changed = False

    for line in original_lines:
        updated = _rewrite_exact_import_statement(line, broken_import, replacement_import)
        if updated != line:
            changed = True
        rewritten_lines.append(updated)

    if changed:
        path.write_text("".join(rewritten_lines), encoding="utf-8")
    return changed


def _module_matches(module_path: str, module_name: str) -> bool:
    return (
        module_path == module_name
        or module_path.endswith(f".{module_name}")
        or module_name.endswith(f".{module_path}")
    )


def _module_path_for_file(workspace_root: Path, path: Path) -> str | None:
    resolved_workspace = workspace_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_workspace)
    except ValueError:
        return None

    if relative_path.name == "__init__.py":
        parts = relative_path.parent.parts
    else:
        parts = relative_path.with_suffix("").parts

    if not parts:
        return None
    return ".".join(parts)


def _rewrite_exact_import_statement(line: str, broken_import: str, replacement_import: str) -> str:
    from_match = re.match(r"^(?P<prefix>\s*from\s+)(?P<module>[A-Za-z0-9_.]+)(?P<suffix>\s+import\b.*)$", line)
    if from_match and from_match.group("module") == broken_import:
        return f"{from_match.group('prefix')}{replacement_import}{from_match.group('suffix')}"

    import_match = re.match(r"^(?P<prefix>\s*import\s+)(?P<module>[A-Za-z0-9_.]+)(?P<suffix>\b.*)$", line)
    if import_match and import_match.group("module") == broken_import:
        return f"{import_match.group('prefix')}{replacement_import}{import_match.group('suffix')}"

    return line
