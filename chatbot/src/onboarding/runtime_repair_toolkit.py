from __future__ import annotations

import re
from pathlib import Path
from typing import Any


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


def repair_python_import_from_traceback(
    *,
    workspace_root: str | Path,
    stderr: str,
) -> dict[str, Any]:
    workspace = Path(workspace_root)
    repair_targets = extract_python_import_targets_from_traceback(
        workspace_root=workspace,
        stderr=stderr,
    )
    repairs: list[dict[str, str]] = []

    for target in repair_targets:
        caller_file = target["caller_file"]
        broken_import = target["broken_import"]
        replacement_import = choose_runtime_import_replacement(
            workspace_root=workspace,
            caller_file=caller_file,
            broken_import=broken_import,
        )
        if not replacement_import or replacement_import == broken_import:
            continue
        changed = rewrite_python_import_line(
            file_path=caller_file,
            broken_import=broken_import,
            replacement_import=replacement_import,
        )
        if changed:
            repairs.append(
                {
                    "caller_file": str(caller_file),
                    "broken_import": broken_import,
                    "replacement_import": replacement_import,
                }
            )

    return {
        "applied": bool(repairs),
        "repairs": repairs,
    }


def extract_python_import_targets_from_traceback(
    *,
    workspace_root: str | Path,
    stderr: str,
) -> list[dict[str, Path | str]]:
    workspace = Path(workspace_root).resolve()
    current_file: Path | None = None
    targets: list[dict[str, Path | str]] = []
    seen: set[tuple[Path, str]] = set()

    for raw_line in stderr.splitlines():
        file_match = re.match(r'^\s*File "(?P<path>[^"]+\.py)", line \d+, in .*$' , raw_line)
        if file_match:
            candidate = Path(file_match.group("path")).resolve()
            try:
                candidate.relative_to(workspace)
            except ValueError:
                current_file = None
            else:
                current_file = candidate
            continue

        if current_file is None:
            continue

        import_match = re.match(
            r"^\s*(?:from|import)\s+(?P<module>[A-Za-z0-9_.]+)(?:\s+import\b.*)?$",
            raw_line,
        )
        if not import_match:
            continue
        broken_import = import_match.group("module")
        key = (current_file, broken_import)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "caller_file": current_file,
                "broken_import": broken_import,
            }
        )

    return targets


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
    line_ending = "\n" if line.endswith("\n") else ""
    line_body = line[:-1] if line_ending else line

    from_match = re.match(r"^(?P<prefix>\s*from\s+)(?P<module>[A-Za-z0-9_.]+)(?P<suffix>\s+import\b.*)$", line_body)
    if from_match and from_match.group("module") == broken_import:
        return f"{from_match.group('prefix')}{replacement_import}{from_match.group('suffix')}{line_ending}"

    import_match = re.match(r"^(?P<prefix>\s*import\s+)(?P<module>[A-Za-z0-9_.]+)(?P<suffix>\b.*)$", line_body)
    if import_match and import_match.group("module") == broken_import:
        return f"{import_match.group('prefix')}{replacement_import}{import_match.group('suffix')}{line_ending}"

    return line
