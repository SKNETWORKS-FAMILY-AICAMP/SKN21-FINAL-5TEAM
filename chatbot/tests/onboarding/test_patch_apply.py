import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

SRC_ROOT = Path(__file__).resolve().parents[3] / "chatbot" / "src"
manifest_module = "chatbot.src.onboarding.manifest"
manifest_spec = importlib.util.spec_from_file_location(
    manifest_module,
    SRC_ROOT / "onboarding" / "manifest.py",
)
manifest = importlib.util.module_from_spec(manifest_spec)
manifest.__package__ = "chatbot.src.onboarding"
manifest_spec.loader.exec_module(manifest)
OverlayManifest = manifest.OverlayManifest
runtime_runner_module = "chatbot.src.onboarding.runtime_runner"
runtime_runner_spec = importlib.util.spec_from_file_location(
    runtime_runner_module,
    SRC_ROOT / "onboarding" / "runtime_runner.py",
)
runtime_runner = importlib.util.module_from_spec(runtime_runner_spec)
runtime_runner.__package__ = "chatbot.src.onboarding"
runtime_runner_spec.loader.exec_module(runtime_runner)
OverlayPatchApplyError = runtime_runner.OverlayPatchApplyError
apply_overlay_patches = runtime_runner.apply_overlay_patches
prepare_runtime_workspace = runtime_runner.prepare_runtime_workspace


def _build_manifest(source_root: Path, patch_targets: list[str]) -> OverlayManifest:
    return OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-15T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": [],
            "patch_targets": patch_targets,
            "docker": {},
            "tests": {},
            "status": "generated",
        }
    )


def test_apply_overlay_patches_updates_runtime_file(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated" / "food" / "run-001"
    runtime_root = tmp_path / "runtime"

    (source_root / "app").mkdir(parents=True)
    original_file = source_root / "app" / "config.txt"
    original_file.write_text("line-1\nline-2\n", encoding="utf-8")

    manifest = _build_manifest(source_root, ["patches/config.patch"])
    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=generated_root,
        runtime_root=runtime_root,
    )
    subprocess.run(["git", "init"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "app/config.txt"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )

    (workspace / "app" / "config.txt").write_text("line-1\nline-2-updated\n", encoding="utf-8")
    diff_result = subprocess.run(
        ["git", "diff", "--", "app/config.txt"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    (generated_root / "patches").mkdir(parents=True)
    patch_path = generated_root / "patches" / "config.patch"
    patch_path.write_text(diff_result.stdout, encoding="utf-8")
    (workspace / "app" / "config.txt").write_text("line-1\nline-2\n", encoding="utf-8")

    apply_overlay_patches(
        manifest=manifest,
        generated_run_root=generated_root,
        workspace_root=workspace,
    )

    assert (workspace / "app" / "config.txt").read_text(encoding="utf-8") == "line-1\nline-2-updated\n"


def test_apply_overlay_patches_raises_clear_error_for_missing_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated" / "food" / "run-001"
    runtime_root = tmp_path / "runtime"

    source_root.mkdir(parents=True)
    generated_root.mkdir(parents=True)

    manifest = _build_manifest(source_root, ["patches/missing.patch"])
    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=generated_root,
        runtime_root=runtime_root,
    )

    with pytest.raises(OverlayPatchApplyError, match="missing.patch"):
        apply_overlay_patches(
            manifest=manifest,
            generated_run_root=generated_root,
            workspace_root=workspace,
        )


def test_apply_overlay_patches_reports_error_for_invalid_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated" / "food" / "run-001"
    runtime_root = tmp_path / "runtime"

    (source_root / "app").mkdir(parents=True)
    original_file = source_root / "app" / "config.txt"
    original_file.write_text("line-1\nline-2\n", encoding="utf-8")

    (generated_root / "patches").mkdir(parents=True)
    patch_path = generated_root / "patches" / "config.patch"
    original_lines = ["line-1\n", "line-2\n"]
    updated_lines = ["line-1\n", "line-2-updated\n"]
    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            updated_lines,
            fromfile="a/app/config.txt",
            tofile="b/app/config.txt",
        )
    )
    diff_lines.extend(
        [
            "@@ -4,2 +4,2 @@\n",
            "-line-4\n",
            "+line-4-updated\n",
        ]
    )
    patch_lines = [
        "diff --git a/app/config.txt b/app/config.txt\n",
        "index 0000001..0000002 100644\n",
    ] + diff_lines
    patch_path.write_text("".join(patch_lines), encoding="utf-8")

    manifest = _build_manifest(source_root, ["patches/config.patch"])
    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=generated_root,
        runtime_root=runtime_root,
    )
    subprocess.run(["git", "init"], cwd=workspace, check=True)

    with pytest.raises(OverlayPatchApplyError, match="config.patch"):
        apply_overlay_patches(
            manifest=manifest,
            generated_run_root=generated_root,
            workspace_root=workspace,
        )
