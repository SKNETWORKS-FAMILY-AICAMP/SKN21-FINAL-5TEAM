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
            ["git", "apply", "--inaccurate-eof", str(patch_path.resolve())],
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

    patch_artifacts = sorted(set(list(manifest.patch_targets) + _discover_simulation_patch_artifacts(generated_root)))
    skipped_patch_artifacts = _filter_redundant_patch_artifacts(patch_artifacts)
    patch_artifacts = [path for path in patch_artifacts if path not in skipped_patch_artifacts]
    applied_patch_artifacts: list[str] = []
    failed_patch_artifacts: list[dict[str, str]] = []

    for relative_patch_path in patch_artifacts:
        patch_path = generated_root / relative_patch_path
        if not patch_path.exists():
            failed_patch_artifacts.append(
                {
                    "path": relative_patch_path,
                    "error": "patch file not found",
                }
            )
            continue
        error = _apply_patch_file(patch_path=patch_path, workspace=workspace)
        if error is None:
            applied_patch_artifacts.append(relative_patch_path)
            continue
        failed_patch_artifacts.append(
            {
                "path": relative_patch_path,
                "error": error,
            }
        )

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
        "applied_patch_artifacts": applied_patch_artifacts,
        "skipped_patch_artifacts": skipped_patch_artifacts,
        "failed_patch_artifacts": failed_patch_artifacts,
        "passed": len(failed_patch_artifacts) == 0,
    }
    output_path = reports / "merge-simulation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _discover_simulation_patch_artifacts(generated_root: Path) -> list[str]:
    patches_root = generated_root / "patches"
    if not patches_root.exists():
        return []
    return sorted(
        path.relative_to(generated_root).as_posix()
        for path in patches_root.rglob("*.patch")
        if path.is_file()
    )


def _apply_patch_file(*, patch_path: Path, workspace: Path) -> str | None:
    attempts = [
        ["git", "apply", "--inaccurate-eof", str(patch_path.resolve())],
        ["patch", "-p1", "-N", "-i", str(patch_path.resolve())],
    ]
    errors: list[str] = []
    for command in attempts:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return None
        errors.append((result.stderr or result.stdout or "unknown error").strip())
    return "\n".join(error for error in errors if error) or "unknown error"


def _filter_redundant_patch_artifacts(patch_artifacts: list[str]) -> list[str]:
    skipped: list[str] = []
    if "patches/proposed.patch" in patch_artifacts and "patches/frontend_widget_mount.patch" in patch_artifacts:
        skipped.append("patches/frontend_widget_mount.patch")
    return skipped
