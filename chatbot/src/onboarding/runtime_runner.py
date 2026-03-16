from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .manifest import OverlayManifest


class OverlayPatchApplyError(Exception):
    pass


def prepare_runtime_workspace(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    runtime_root: str | Path,
) -> Path:
    source_root = Path(manifest.source_root)
    generated_root = Path(generated_run_root)
    runtime_base = Path(runtime_root)
    workspace = runtime_base / manifest.site / manifest.run_id / "workspace"

    if workspace.exists():
        shutil.rmtree(workspace)

    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, workspace)

    overlay_files_root = generated_root / "files"
    if overlay_files_root.exists():
        for item in overlay_files_root.rglob("*"):
            if item.is_dir():
                continue
            relative_path = item.relative_to(overlay_files_root)
            target_path = workspace / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_path)

    return workspace


def apply_overlay_patches(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    workspace_root: str | Path,
) -> None:
    generated_root = Path(generated_run_root)
    workspace = Path(workspace_root)

    for relative_patch_path in manifest.patch_targets:
        patch_path = generated_root / relative_patch_path
        if not patch_path.exists():
            raise OverlayPatchApplyError(f"Patch file not found: {patch_path}")

        result = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise OverlayPatchApplyError(
                f"Failed to apply patch {patch_path.name}: {stderr or 'unknown error'}"
            )


def simulate_runtime_merge(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    runtime_workspace: str | Path,
    report_root: str | Path,
) -> Path:
    generated_root = Path(generated_run_root)
    workspace = Path(runtime_workspace)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": manifest.run_id,
        "site": manifest.site,
        "workspace_root": str(workspace),
        "applied_generated_files": sorted(
            str(path.relative_to(generated_root / "files").as_posix())
            for path in (generated_root / "files").rglob("*")
            if path.is_file()
        )
        if (generated_root / "files").exists()
        else [],
        "applied_patch_artifacts": sorted(manifest.patch_targets),
    }
    output_path = reports / "merge-simulation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
