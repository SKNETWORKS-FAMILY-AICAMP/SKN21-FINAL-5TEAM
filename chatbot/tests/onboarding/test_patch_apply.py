import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.manifest import OverlayManifest
from chatbot.src.onboarding.runtime_runner import (
    OverlayPatchApplyError,
    apply_overlay_patches,
    prepare_runtime_workspace,
)


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

    (generated_root / "patches").mkdir(parents=True)
    patch_path = generated_root / "patches" / "config.patch"
    patch_path.write_text(
        """--- a/app/config.txt
+++ b/app/config.txt
@@ -1,2 +1,2 @@
 line-1
-line-2
+line-2-updated
""",
        encoding="utf-8",
    )

    manifest = _build_manifest(source_root, ["patches/config.patch"])
    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=generated_root,
        runtime_root=runtime_root,
    )

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
