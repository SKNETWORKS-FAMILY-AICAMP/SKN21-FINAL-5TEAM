from __future__ import annotations

import difflib
import json
from pathlib import Path


def _read_text_or_empty(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def export_runtime_patch(
    *,
    source_root: str | Path,
    runtime_workspace: str | Path,
    report_root: str | Path,
    patch_name: str = "approved.patch",
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
        source_file = source / relative
        source_lines = _read_text_or_empty(source_file)
        runtime_lines = _read_text_or_empty(runtime_file)

        if source_lines == runtime_lines:
            continue

        changed_files.append(relative.as_posix())
        diff = difflib.unified_diff(
            source_lines,
            runtime_lines,
            fromfile=f"a/{relative.as_posix()}",
            tofile=f"b/{relative.as_posix()}",
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
