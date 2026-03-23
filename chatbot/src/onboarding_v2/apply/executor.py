from __future__ import annotations

import shutil
from pathlib import Path

from chatbot.src.onboarding.onboarding_ignore import DEFAULT_IGNORED_PARTS
from chatbot.src.onboarding.workspace_editor import apply_direct_edit_operations
from chatbot.src.onboarding_v2.models.compile import EditProgram, SupportingArtifactBundle
from chatbot.src.onboarding_v2.models.validation import ApplyBundleResult, ApplyResult


def apply_edit_program(
    *,
    source_root: str | Path,
    runtime_root: str | Path,
    site: str,
    run_id: str,
    edit_program: EditProgram,
) -> ApplyResult:
    source_root = Path(source_root)
    runtime_base = Path(runtime_root)
    workspace = runtime_base / site / run_id / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, workspace, ignore=_ignore_runtime_copy_directory)

    applied_files: set[str] = set()
    applied_bundles: list[ApplyBundleResult] = []
    failed_bundles: list[ApplyBundleResult] = []

    for supporting_bundle in edit_program.supporting_artifact_bundles:
        _write_supporting_file(workspace=workspace, bundle=supporting_bundle)
        applied_files.add(supporting_bundle.path)
        applied_bundles.append(
            ApplyBundleResult(
                bundle_id=supporting_bundle.bundle_id,
                passed=True,
                details={"path": supporting_bundle.path},
            )
        )

    ordered_bundles = [
        *edit_program.backend_wiring_bundles,
        *edit_program.frontend_api_bundles,
        *edit_program.frontend_mount_bundles,
    ]
    for bundle in ordered_bundles:
        for supporting in getattr(bundle, "supporting_files", []):
            _write_supporting_file(workspace=workspace, bundle=supporting)
            applied_files.add(supporting.path)
        try:
            result = apply_direct_edit_operations(
                workspace_root=workspace,
                operations=[
                    operation.model_dump(exclude_none=True)
                    for operation in bundle.operations
                ],
            )
        except Exception as exc:
            failed_bundles.append(
                ApplyBundleResult(
                    bundle_id=bundle.bundle_id,
                    passed=False,
                    details={"error": str(exc)},
                )
            )
            break
        for edit in result.get("applied_edits") or []:
            path = str(edit.get("path") or "").strip()
            if path:
                applied_files.add(path)
        applied_bundles.append(
            ApplyBundleResult(
                bundle_id=bundle.bundle_id,
                passed=True,
                details={"applied_edit_count": len(result.get("applied_edits") or [])},
            )
        )

    return ApplyResult(
        workspace_path=str(workspace),
        passed=not failed_bundles,
        applied_files=sorted(applied_files),
        applied_bundles=applied_bundles,
        failed_bundles=failed_bundles,
    )


def _write_supporting_file(*, workspace: Path, bundle: SupportingArtifactBundle) -> None:
    path = workspace / bundle.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.content, encoding="utf-8")


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in DEFAULT_IGNORED_PARTS}
