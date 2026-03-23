from __future__ import annotations

import difflib
import shutil
from pathlib import Path

from chatbot.src.onboarding.exporter import IGNORED_EXPORT_PARTS
from chatbot.src.onboarding.runtime_runner import _apply_patch_file
from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.validation import ReplayResult
from chatbot.src.onboarding_v2.storage import ArtifactStore


def export_and_replay(
    *,
    source_root: str | Path,
    runtime_workspace: str | Path,
    runtime_root: str | Path,
    run_root: str | Path,
    site: str,
    run_id: str,
    artifact_store: ArtifactStore,
) -> tuple[ArtifactRef, ReplayResult, ArtifactRef]:
    source_root = Path(source_root)
    runtime_workspace = Path(runtime_workspace)
    runtime_root = Path(runtime_root)
    run_root = Path(run_root)

    patch_content = _generate_patch_content(source_root=source_root, runtime_workspace=runtime_workspace)
    patch_ref = artifact_store.write_text_artifact(
        stage="export",
        artifact_type="approved-patch",
        content=patch_content,
        suffix=".patch",
    )
    patch_path = run_root / "artifacts" / "06-export" / "approved-patch" / patch_ref.path

    replay_workspace = runtime_root / site / run_id / "export-replay-workspace"
    if replay_workspace.exists():
        shutil.rmtree(replay_workspace)
    replay_workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, replay_workspace, ignore=_ignore_runtime_copy_directory)

    failed_patch_artifacts: list[dict[str, object]] = []
    applied_patch_artifacts: list[str] = []
    if patch_content.strip():
        failure = _apply_patch_file(patch_path=patch_path, workspace=replay_workspace)
        if failure is None:
            applied_patch_artifacts.append(f"approved-patch/{patch_ref.path}")
        else:
            failed_patch_artifacts.append({"path": str(patch_path), **failure})

    replay_result = ReplayResult(
        replay_workspace_path=str(replay_workspace),
        patch_path=str(patch_path),
        passed=not failed_patch_artifacts,
        applied_patch_artifacts=applied_patch_artifacts,
        failed_patch_artifacts=failed_patch_artifacts,
    )
    replay_ref = artifact_store.write_json_artifact(
        stage="export",
        artifact_type="replay-result",
        payload=replay_result.model_dump(mode="json"),
        producer="exporter",
        input_artifact_refs=[patch_ref],
    )
    return patch_ref, replay_result, replay_ref


def _generate_patch_content(*, source_root: Path, runtime_workspace: Path) -> str:
    patch_chunks: list[str] = []
    for runtime_file in sorted(path for path in runtime_workspace.rglob("*") if path.is_file()):
        relative = runtime_file.relative_to(runtime_workspace)
        if any(part in IGNORED_EXPORT_PARTS for part in relative.parts):
            continue
        source_file = source_root / relative
        source_lines = _read_text_lines(source_file)
        runtime_lines = _read_text_lines(runtime_file)
        if source_lines == runtime_lines:
            continue
        relative_path = relative.as_posix()
        diff = difflib.unified_diff(
            source_lines,
            runtime_lines,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
        patch_chunks.append("".join(diff))
    return "".join(patch_chunks)


def _read_text_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return []


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_EXPORT_PARTS}
