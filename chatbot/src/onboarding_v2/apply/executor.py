from __future__ import annotations

import shutil
from pathlib import Path

from chatbot.src.onboarding.onboarding_ignore import runtime_copy_ignored_names
from chatbot.src.onboarding.workspace_editor import apply_direct_edit_operations
from chatbot.src.onboarding_v2.models.compile import (
    ChatbotBridgeBundle,
    EditProgram,
    SupportingArtifactBundle,
)
from chatbot.src.onboarding_v2.models.validation import ApplyBundleResult, ApplyResult


def apply_edit_program(
    *,
    host_source_root: str | Path,
    chatbot_source_root: str | Path,
    runtime_root: str | Path,
    site: str,
    run_id: str,
    edit_program: EditProgram,
) -> ApplyResult:
    host_source_root = Path(host_source_root)
    chatbot_source_root = Path(chatbot_source_root)
    runtime_base = Path(runtime_root)
    run_root = runtime_base / site / run_id
    snapshot_root = run_root / "source-snapshot"
    workspace_root = run_root / "workspace"
    host_snapshot = snapshot_root / "host"
    chatbot_snapshot = snapshot_root / "chatbot"
    host_workspace = workspace_root / "host"
    chatbot_workspace = workspace_root / "chatbot"
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    run_root.mkdir(parents=True, exist_ok=True)
    _copy_runtime_tree(source_root=host_source_root, target_root=host_snapshot)
    _copy_runtime_tree(source_root=chatbot_source_root, target_root=chatbot_snapshot)
    _copy_runtime_tree(source_root=host_source_root, target_root=host_workspace)
    _copy_runtime_tree(source_root=chatbot_source_root, target_root=chatbot_workspace)

    host_applied_files: set[str] = set()
    chatbot_applied_files: set[str] = set()
    applied_bundles: list[ApplyBundleResult] = []
    failed_bundles: list[ApplyBundleResult] = []

    _apply_supporting_files(
        workspace=host_workspace,
        bundles=edit_program.host_program.supporting_artifact_bundles,
        applied_files=host_applied_files,
        applied_bundles=applied_bundles,
    )
    _apply_supporting_files(
        workspace=chatbot_workspace,
        bundles=edit_program.chatbot_program.supporting_artifact_bundles,
        applied_files=chatbot_applied_files,
        applied_bundles=applied_bundles,
    )

    host_bundles = [
        *edit_program.host_program.backend_wiring_bundles,
        *edit_program.host_program.frontend_api_bundles,
        *edit_program.host_program.frontend_mount_bundles,
    ]
    for bundle in host_bundles:
        if not _apply_operations_bundle(
            workspace=host_workspace,
            bundle=bundle,
            applied_files=host_applied_files,
            applied_bundles=applied_bundles,
            failed_bundles=failed_bundles,
        ):
            break

    if not failed_bundles:
        for bundle in edit_program.chatbot_program.bridge_bundles:
            if not _apply_operations_bundle(
                workspace=chatbot_workspace,
                bundle=bundle,
                applied_files=chatbot_applied_files,
                applied_bundles=applied_bundles,
                failed_bundles=failed_bundles,
            ):
                break

    return ApplyResult(
        workspace_path=str(workspace_root),
        host_workspace_path=str(host_workspace),
        chatbot_workspace_path=str(chatbot_workspace),
        host_source_snapshot_path=str(host_snapshot),
        chatbot_source_snapshot_path=str(chatbot_snapshot),
        passed=not failed_bundles,
        applied_files=sorted(
            [f"host:{path}" for path in host_applied_files]
            + [f"chatbot:{path}" for path in chatbot_applied_files]
        ),
        host_applied_files=sorted(host_applied_files),
        chatbot_applied_files=sorted(chatbot_applied_files),
        applied_bundles=applied_bundles,
        failed_bundles=failed_bundles,
    )


def _apply_supporting_files(
    *,
    workspace: Path,
    bundles: list[SupportingArtifactBundle],
    applied_files: set[str],
    applied_bundles: list[ApplyBundleResult],
) -> None:
    for bundle in bundles:
        _write_supporting_file(workspace=workspace, bundle=bundle)
        applied_files.add(bundle.path)
        applied_bundles.append(
            ApplyBundleResult(
                bundle_id=bundle.bundle_id,
                passed=True,
                details={"path": bundle.path},
            )
        )


def _apply_operations_bundle(
    *,
    workspace: Path,
    bundle: ChatbotBridgeBundle | object,
    applied_files: set[str],
    applied_bundles: list[ApplyBundleResult],
    failed_bundles: list[ApplyBundleResult],
) -> bool:
    for supporting in getattr(bundle, "supporting_files", []):
        _write_supporting_file(workspace=workspace, bundle=supporting)
        applied_files.add(supporting.path)
    try:
        result = apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                operation.model_dump(exclude_none=True)
                for operation in getattr(bundle, "operations", [])
            ],
        )
    except Exception as exc:
        failed_bundles.append(
            ApplyBundleResult(
                bundle_id=getattr(bundle, "bundle_id", "unknown"),
                passed=False,
                details={"error": str(exc)},
            )
        )
        return False
    for edit in result.get("applied_edits") or []:
        path = str(edit.get("path") or "").strip()
        if path:
            applied_files.add(path)
    applied_bundles.append(
        ApplyBundleResult(
            bundle_id=getattr(bundle, "bundle_id", "unknown"),
            passed=True,
            details={"applied_edit_count": len(result.get("applied_edits") or [])},
        )
    )
    return True


def _write_supporting_file(*, workspace: Path, bundle: SupportingArtifactBundle) -> None:
    path = workspace / bundle.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.content, encoding="utf-8")


def _copy_runtime_tree(*, source_root: Path, target_root: Path) -> None:
    shutil.copytree(source_root, target_root, ignore=_ignore_runtime_copy_directory)


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return runtime_copy_ignored_names(_, names)
