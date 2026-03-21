from __future__ import annotations

import difflib
import json
from pathlib import Path

IGNORED_EXPORT_PARTS = {
    ".venv",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
}


def _read_text_or_empty(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return []


def export_runtime_patch(
    *,
    source_root: str | Path,
    runtime_workspace: str | Path,
    report_root: str | Path,
    patch_name: str = "approved.patch",
    allowed_targets: set[str] | None = None,
    strategy_provenance: dict[str, str] | None = None,
    recovery_provenance: dict[str, str] | None = None,
) -> Path:
    source = Path(source_root)
    runtime = Path(runtime_workspace)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)

    patch_chunks: list[str] = []
    changed_files: list[str] = []
    runtime_files = [p for p in runtime.rglob("*") if p.is_file()]

    for runtime_file in sorted(runtime_files):
        relative = runtime_file.relative_to(runtime)
        if _should_ignore_runtime_export(relative):
            continue
        source_file = source / relative
        source_lines = _read_text_or_empty(source_file)
        runtime_lines = _read_text_or_empty(runtime_file)

        if source_lines == runtime_lines:
            continue
        relative_path = relative.as_posix()
        if allowed_targets is not None and relative_path not in allowed_targets:
            continue

        changed_files.append(relative_path)
        diff = difflib.unified_diff(
            source_lines,
            runtime_lines,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
        patch_chunks.append("".join(diff))

    patch_path = reports / patch_name
    patch_path.write_text("".join(patch_chunks), encoding="utf-8")
    metadata_path = reports / "export-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "patch_path": str(patch_path),
                "changed_files": changed_files,
                "export_source": "runtime",
                "strategy_provenance": strategy_provenance or {},
                "recovery_provenance": recovery_provenance or {},
                "pr": {
                    "title": f"[Onboarding] Review export for {runtime.parent.name}",
                    "body": "Review the exported onboarding patch and promote it after approval.",
                    "head_branch": f"onboarding/{runtime.parent.name}",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return patch_path


def _should_ignore_runtime_export(relative: Path) -> bool:
    return any(part in IGNORED_EXPORT_PARTS for part in relative.parts)


def export_patch_artifact(
    *,
    patch_path: str | Path,
    report_root: str | Path,
    export_source: str,
    patch_name: str = "approved.patch",
    strategy_provenance: dict[str, str] | None = None,
    recovery_provenance: dict[str, str] | None = None,
) -> Path:
    source_patch = Path(patch_path)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)

    approved_patch = reports / patch_name
    content = source_patch.read_text(encoding="utf-8") if source_patch.exists() else ""
    approved_patch.write_text(content, encoding="utf-8")

    metadata_path = reports / "export-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "patch_path": str(approved_patch),
                "source_patch_path": str(source_patch),
                "changed_files": _extract_changed_files_from_patch(content),
                "export_source": export_source,
                "strategy_provenance": strategy_provenance or {},
                "recovery_provenance": recovery_provenance or {},
                "pr": {
                    "title": f"[Onboarding] Review export for {reports.parent.name}",
                    "body": "Review the exported onboarding patch and promote it after approval.",
                    "head_branch": f"onboarding/{reports.parent.name}",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return approved_patch


def _extract_changed_files_from_patch(content: str) -> list[str]:
    changed_files: list[str] = []
    for line in content.splitlines():
        if line.startswith("+++ b/"):
            changed_files.append(line.removeprefix("+++ b/"))
    return changed_files
