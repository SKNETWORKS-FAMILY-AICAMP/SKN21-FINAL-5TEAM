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
    host_source_root: str | Path,
    chatbot_source_root: str | Path,
    host_runtime_workspace: str | Path,
    chatbot_runtime_workspace: str | Path,
    runtime_root: str | Path,
    run_root: str | Path,
    site: str,
    run_id: str,
    artifact_store: ArtifactStore,
) -> tuple[ArtifactRef, ReplayResult, ArtifactRef]:
    host_source_root = Path(host_source_root)
    chatbot_source_root = Path(chatbot_source_root)
    host_runtime_workspace = Path(host_runtime_workspace)
    chatbot_runtime_workspace = Path(chatbot_runtime_workspace)
    runtime_root = Path(runtime_root)
    run_root = Path(run_root)

    host_patch_content = _generate_patch_content(
        source_root=host_source_root,
        runtime_workspace=host_runtime_workspace,
    )
    chatbot_patch_content = _generate_patch_content(
        source_root=chatbot_source_root,
        runtime_workspace=chatbot_runtime_workspace,
    )
    host_patch_ref = artifact_store.write_text_artifact(
        stage="export",
        artifact_type="host-approved.patch",
        content=host_patch_content,
        suffix=".patch",
    )
    chatbot_patch_ref = artifact_store.write_text_artifact(
        stage="export",
        artifact_type="chatbot-approved.patch",
        content=chatbot_patch_content,
        suffix=".patch",
    )
    host_patch_path = run_root / "artifacts" / "06-export" / "host-approved.patch" / host_patch_ref.path
    chatbot_patch_path = run_root / "artifacts" / "06-export" / "chatbot-approved.patch" / chatbot_patch_ref.path

    replay_root = runtime_root / site / run_id / "export-replay-workspace"
    host_replay_workspace = replay_root / "host"
    chatbot_replay_workspace = replay_root / "chatbot"
    if replay_root.exists():
        shutil.rmtree(replay_root)
    replay_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(host_source_root, host_replay_workspace, ignore=_ignore_runtime_copy_directory)
    shutil.copytree(chatbot_source_root, chatbot_replay_workspace, ignore=_ignore_runtime_copy_directory)

    failed_patch_artifacts: list[dict[str, object]] = []
    applied_patch_artifacts: list[str] = []
    _apply_patch_if_needed(
        patch_content=host_patch_content,
        patch_path=host_patch_path,
        workspace=host_replay_workspace,
        artifact_label=f"host-approved.patch/{host_patch_ref.path}",
        applied_patch_artifacts=applied_patch_artifacts,
        failed_patch_artifacts=failed_patch_artifacts,
    )
    _apply_patch_if_needed(
        patch_content=chatbot_patch_content,
        patch_path=chatbot_patch_path,
        workspace=chatbot_replay_workspace,
        artifact_label=f"chatbot-approved.patch/{chatbot_patch_ref.path}",
        applied_patch_artifacts=applied_patch_artifacts,
        failed_patch_artifacts=failed_patch_artifacts,
    )

    replay_result = ReplayResult(
        replay_workspace_path=str(replay_root),
        host_replay_workspace_path=str(host_replay_workspace),
        chatbot_replay_workspace_path=str(chatbot_replay_workspace),
        host_patch_path=str(host_patch_path),
        chatbot_patch_path=str(chatbot_patch_path),
        passed=not failed_patch_artifacts,
        applied_patch_artifacts=applied_patch_artifacts,
        failed_patch_artifacts=failed_patch_artifacts,
    )
    replay_ref = artifact_store.write_json_artifact(
        stage="export",
        artifact_type="replay-result",
        payload=replay_result.model_dump(mode="json"),
        producer="exporter",
        input_artifact_refs=[host_patch_ref, chatbot_patch_ref],
    )
    export_bundle_ref = artifact_store.write_json_artifact(
        stage="export",
        artifact_type="export-bundle",
        payload={
            "host_patch_artifact": host_patch_ref.model_dump(mode="json"),
            "chatbot_patch_artifact": chatbot_patch_ref.model_dump(mode="json"),
            "replay_artifact": replay_ref.model_dump(mode="json"),
            "replay_passed": replay_result.passed,
        },
        producer="exporter",
        input_artifact_refs=[host_patch_ref, chatbot_patch_ref, replay_ref],
    )
    return export_bundle_ref, replay_result, replay_ref


def _apply_patch_if_needed(
    *,
    patch_content: str,
    patch_path: Path,
    workspace: Path,
    artifact_label: str,
    applied_patch_artifacts: list[str],
    failed_patch_artifacts: list[dict[str, object]],
) -> None:
    if not patch_content.strip():
        return
    failure = _apply_patch_file(patch_path=patch_path, workspace=workspace)
    if failure is None:
        applied_patch_artifacts.append(artifact_label)
    else:
        failed_patch_artifacts.append({"path": str(patch_path), **failure})


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
