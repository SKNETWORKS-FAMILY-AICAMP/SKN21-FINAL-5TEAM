from __future__ import annotations

import errno
import shutil
from pathlib import Path
from typing import Any

from chatbot.src.onboarding.onboarding_ignore import runtime_copy_ignored_names
from chatbot.src.onboarding.workspace_editor import apply_direct_edit_operations
from chatbot.src.onboarding_v2.models.compile import (
    ChatbotBridgeBundle,
    EditProgram,
    SupportingArtifactBundle,
)
from chatbot.src.onboarding_v2.models.validation import ApplyBundleResult, ApplyResult


class RuntimeCopyError(Exception):
    def __init__(self, summary: str, *, details: dict[str, Any]) -> None:
        super().__init__(summary)
        self.summary = summary
        self.details = details


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
    host_applied_files: set[str] = set()
    chatbot_applied_files: set[str] = set()
    applied_bundles: list[ApplyBundleResult] = []
    failed_bundles: list[ApplyBundleResult] = []
    failure_summary: str | None = None
    failure_details: dict[str, Any] = {}

    try:
        _copy_runtime_tree(
            source_root=host_source_root,
            target_root=host_snapshot,
            copy_context="host source snapshot",
        )
        _copy_runtime_tree(
            source_root=chatbot_source_root,
            target_root=chatbot_snapshot,
            copy_context="chatbot source snapshot",
        )
        _copy_runtime_tree(
            source_root=host_source_root,
            target_root=host_workspace,
            copy_context="host runtime workspace",
        )
        _copy_runtime_tree(
            source_root=chatbot_source_root,
            target_root=chatbot_workspace,
            copy_context="chatbot runtime workspace",
        )
    except RuntimeCopyError as exc:
        failure_summary = exc.summary
        failure_details = dict(exc.details)
        failed_bundles.append(
            ApplyBundleResult(
                bundle_id="runtime_copy",
                passed=False,
                details=failure_details,
            )
        )

    if not failed_bundles:
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
        failure_summary=failure_summary,
        failure_details=failure_details,
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


def _copy_runtime_tree(
    *,
    source_root: Path,
    target_root: Path,
    copy_context: str,
) -> None:
    try:
        shutil.copytree(source_root, target_root, ignore=_ignore_runtime_copy_directory)
    except (shutil.Error, OSError) as exc:
        raise RuntimeCopyError(
            _runtime_copy_failure_summary(exc),
            details=_runtime_copy_failure_details(
                exc,
                source_root=source_root,
                target_root=target_root,
                copy_context=copy_context,
            ),
        ) from exc


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return runtime_copy_ignored_names(_, names)


def _runtime_copy_failure_summary(exc: Exception) -> str:
    if _is_no_space_left_error(exc):
        return "runtime copy failed: no space left on device"
    return f"runtime copy failed: {exc}"


def _runtime_copy_failure_details(
    exc: Exception,
    *,
    source_root: Path,
    target_root: Path,
    copy_context: str,
) -> dict[str, Any]:
    offending_paths = _sample_offending_paths(exc, source_root=source_root, target_root=target_root)
    details: dict[str, Any] = {
        "copy_context": copy_context,
        "source_root": str(source_root),
        "target_root": str(target_root),
        "failure_code": "runtime_copy_failed",
        "offending_paths": offending_paths,
    }
    if _is_no_space_left_error(exc):
        details["failure_code"] = "runtime_copy_no_space_left"
    return details


def _is_no_space_left_error(exc: Exception) -> bool:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return True
    if isinstance(exc, shutil.Error):
        entries = exc.args[0] if exc.args else []
        return any("no space left on device" in str(item).lower() for item in entries)
    return "no space left on device" in str(exc).lower()


def _sample_offending_paths(
    exc: Exception,
    *,
    source_root: Path,
    target_root: Path,
    limit: int = 5,
) -> list[str]:
    del target_root
    samples: list[str] = []
    if isinstance(exc, shutil.Error):
        entries = exc.args[0] if exc.args else []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or not entry:
                continue
            sample = _normalize_offending_path(entry[0], source_root=source_root)
            if sample and sample not in samples:
                samples.append(sample)
            if len(samples) >= limit:
                return samples
    if isinstance(exc, OSError):
        sample = _normalize_offending_path(getattr(exc, "filename", None), source_root=source_root)
        if sample:
            samples.append(sample)
    return samples


def _normalize_offending_path(path_value: str | None, *, source_root: Path) -> str | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        return path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
