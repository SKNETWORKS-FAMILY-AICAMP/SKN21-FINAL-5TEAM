from __future__ import annotations

import json
from pathlib import Path


TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}


def build_codebase_map(*, source_root: str | Path) -> dict:
    root = Path(source_root)
    files: list[str] = []
    candidate_edit_targets: list[dict[str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(relative)

        reason = _infer_reason(relative, path)
        if reason is not None:
            candidate_edit_targets.append(
                {
                    "path": relative,
                    "reason": reason,
                }
            )

    return {
        "source_root": str(root),
        "files": files,
        "candidate_edit_targets": candidate_edit_targets,
    }


def write_codebase_map(*, source_root: str | Path, output_path: str | Path) -> Path:
    payload = build_codebase_map(source_root=source_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _infer_reason(relative_path: str, path: Path) -> str | None:
    lower = relative_path.lower()
    if "views.py" in lower or "routes" in lower or "urls.py" in lower:
        return "backend route or handler candidate"
    if path.suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"} and "app" in path.stem.lower():
        return "frontend mount or integration candidate"
    return None
