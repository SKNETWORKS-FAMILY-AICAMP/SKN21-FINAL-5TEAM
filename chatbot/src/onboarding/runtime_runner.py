from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .debug_logging import append_onboarding_event
from .manifest import OverlayManifest
from .onboarding_ignore import runtime_copy_ignored_names
from .workspace_editor import apply_direct_edit_operations


class OverlayPatchApplyError(Exception):
    pass


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return runtime_copy_ignored_names(_, names)


def prepare_runtime_workspace(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    runtime_root: str | Path,
    workspace_name: str = "workspace",
) -> Path:
    source_root = Path(manifest.source_root)
    generated_root = Path(generated_run_root)
    runtime_base = Path(runtime_root)
    workspace = runtime_base / manifest.site / manifest.run_id / workspace_name

    if workspace.exists():
        _remove_runtime_workspace(workspace)

    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, workspace, ignore=_ignore_runtime_copy_directory)

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


def _remove_runtime_workspace(workspace: Path, *, attempts: int = 3, delay_seconds: float = 0.2) -> None:
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(workspace)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error


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

        failure = _apply_patch_file(patch_path=patch_path, workspace=workspace)
        if failure is not None:
            raise OverlayPatchApplyError(
                f"Failed to apply patch {patch_path.name}: {str(failure.get('error') or 'unknown error')}"
            )


def apply_overlay_edit_artifacts(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    workspace_root: str | Path,
    report_root: str | Path,
) -> Path:
    generated_root = Path(generated_run_root)
    workspace = Path(workspace_root)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    append_onboarding_event(
        report_root=reports,
        run_id=manifest.run_id,
        component="runtime_runner",
        stage="validation",
        event="edit_application_started",
        severity="info",
        summary="edit artifact application started",
        source="system",
        details={"workspace_root": str(workspace)},
    )

    applied_edit_artifacts: list[str] = []
    applied_edits: list[dict[str, str]] = []
    failed_edit_artifacts: list[dict[str, str]] = []

    for relative_edit_path in manifest.edit_artifacts:
        edit_path = generated_root / relative_edit_path
        if not edit_path.exists():
            failed_edit_artifacts.append(
                {
                    "path": relative_edit_path,
                    "error": "edit artifact not found",
                }
            )
            break

        try:
            payload = json.loads(edit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failed_edit_artifacts.append(
                {
                    "path": relative_edit_path,
                    "error": f"invalid edit artifact: {exc.msg}",
                }
            )
            break

        operations = payload.get("operations") or []
        if not operations:
            applied_edit_artifacts.append(relative_edit_path)
            continue

        try:
            result = apply_direct_edit_operations(workspace_root=workspace, operations=list(operations))
        except Exception as exc:
            failed_edit_artifacts.append(
                {
                    "path": relative_edit_path,
                    "error": str(exc) or "edit application failed",
                }
            )
            break

        applied_edit_artifacts.append(relative_edit_path)
        applied_edits.extend(result.get("applied_edits") or [])

    payload = {
        "run_id": manifest.run_id,
        "site": manifest.site,
        "workspace_root": str(workspace),
        "applied_edit_artifacts": applied_edit_artifacts,
        "applied_edits": applied_edits,
        "failed_edit_artifacts": failed_edit_artifacts,
        "passed": len(failed_edit_artifacts) == 0,
    }
    output_path = reports / "edit-execution.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_onboarding_event(
        report_root=reports,
        run_id=manifest.run_id,
        component="runtime_runner",
        stage="validation",
        event="edit_application_completed",
        severity="info" if payload["passed"] else "warn",
        summary="edit artifact application completed",
        source="runtime",
        details={
            "passed": payload["passed"],
            "applied_edit_count": len(applied_edits),
            "failed_edit_count": len(failed_edit_artifacts),
            "report_path": str(output_path),
        },
    )
    return output_path


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
    append_onboarding_event(
        report_root=reports,
        run_id=manifest.run_id,
        component="runtime_runner",
        stage="validation",
        event="simulation_started",
        severity="info",
        summary="runtime merge simulation started",
        source="system",
        details={"workspace_root": str(workspace)},
    )

    patch_artifacts = list(manifest.patch_targets)
    skipped_patch_artifacts = _filter_redundant_patch_artifacts(
        patch_artifacts,
        has_direct_edit_artifacts=bool(manifest.edit_artifacts),
    )
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
        failure = _apply_patch_file(patch_path=patch_path, workspace=workspace)
        if failure is None:
            applied_patch_artifacts.append(relative_patch_path)
            continue
        failed_patch_artifacts.append({"path": relative_patch_path, **failure})
        append_onboarding_event(
            report_root=reports,
            run_id=manifest.run_id,
            component="runtime_runner",
            stage="validation",
            event="hard_fallback_used",
            severity="warn",
            summary="runtime merge patch failed",
            source="hard_fallback",
            recovery={"applied": False, "reason": str(failure.get("error") or "patch_apply_failed")},
            details={"patch_artifact": relative_patch_path, "target_files": failure.get("target_files") or []},
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
    append_onboarding_event(
        report_root=reports,
        run_id=manifest.run_id,
        component="runtime_runner",
        stage="validation",
        event="simulation_completed",
        severity="info" if payload["passed"] else "warn",
        summary="runtime merge simulation completed",
        source="runtime",
        details={
            "passed": payload["passed"],
            "applied_patch_count": len(applied_patch_artifacts),
            "failed_patch_count": len(failed_patch_artifacts),
            "report_path": str(output_path),
        },
    )
    return output_path


def simulate_candidate_patch_merge(
    *,
    manifest: OverlayManifest,
    generated_run_root: str | Path,
    runtime_root: str | Path,
    report_root: str | Path,
    patch_artifact: str,
    report_name: str,
) -> Path:
    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=generated_run_root,
        runtime_root=runtime_root,
        workspace_name=Path(report_name).stem.replace(".", "-") + "-workspace",
    )
    generated_root = Path(generated_run_root)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    patch_path = generated_root / patch_artifact
    failed_patch_artifacts: list[dict[str, object]] = []
    applied_patch_artifacts: list[str] = []

    if not patch_path.exists():
        failed_patch_artifacts.append({"path": patch_artifact, "error": "patch file not found"})
    else:
        failure = _apply_patch_file(patch_path=patch_path, workspace=workspace)
        if failure is None:
            applied_patch_artifacts.append(patch_artifact)
        else:
            failed_patch_artifacts.append({"path": patch_artifact, **failure})

    payload = {
        "run_id": manifest.run_id,
        "site": manifest.site,
        "workspace_root": str(workspace),
        "candidate_patch": patch_artifact,
        "applied_patch_artifacts": applied_patch_artifacts,
        "failed_patch_artifacts": failed_patch_artifacts,
        "passed": len(failed_patch_artifacts) == 0,
    }
    output_path = reports / report_name
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def simulate_exported_patch_replay(
    *,
    source_root: str | Path,
    runtime_root: str | Path,
    report_root: str | Path,
    patch_path: str | Path,
    site: str,
    run_id: str,
) -> Path:
    source = Path(source_root)
    runtime_base = Path(runtime_root)
    reports = Path(report_root)
    reports.mkdir(parents=True, exist_ok=True)
    replay_workspace = runtime_base / site / run_id / "export-replay-workspace"

    append_onboarding_event(
        report_root=reports,
        run_id=run_id,
        component="runtime_runner",
        stage="export",
        event="export_replay_validation_started",
        severity="info",
        summary="export replay validation started",
        source="system",
        details={"workspace_root": str(replay_workspace)},
    )

    if replay_workspace.exists():
        _remove_runtime_workspace(replay_workspace)
    replay_workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, replay_workspace, ignore=_ignore_runtime_copy_directory)

    artifact_path = Path(patch_path)
    run_root = reports.parent
    relative_patch_path = (
        artifact_path.relative_to(run_root).as_posix()
        if artifact_path.is_relative_to(run_root)
        else artifact_path.name
    )
    applied_patch_artifacts: list[str] = []
    failed_patch_artifacts: list[dict[str, object]] = []

    if not artifact_path.exists():
        failed_patch_artifacts.append({"path": relative_patch_path, "error": "patch file not found"})
    else:
        content = artifact_path.read_text(encoding="utf-8")
        if content.strip():
            failure = _apply_patch_file(patch_path=artifact_path, workspace=replay_workspace)
            if failure is None:
                applied_patch_artifacts.append(relative_patch_path)
            else:
                failed_patch_artifacts.append({"path": relative_patch_path, **failure})

    payload = {
        "run_id": run_id,
        "site": site,
        "workspace_root": str(replay_workspace),
        "patch_path": str(artifact_path),
        "applied_patch_artifacts": applied_patch_artifacts,
        "failed_patch_artifacts": failed_patch_artifacts,
        "passed": len(failed_patch_artifacts) == 0,
    }
    output_path = reports / "export-replay-validation.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_onboarding_event(
        report_root=reports,
        run_id=run_id,
        component="runtime_runner",
        stage="export",
        event="export_replay_validation_completed",
        severity="info" if payload["passed"] else "warn",
        summary="export replay validation completed",
        source="runtime",
        details={
            "passed": payload["passed"],
            "report_path": str(output_path),
            "failed_patch_count": len(failed_patch_artifacts),
        },
    )
    return output_path


def _discover_simulation_patch_artifacts(generated_root: Path) -> list[str]:
    patches_root = generated_root / "patches"
    if not patches_root.exists():
        return []
    return sorted(
        path.relative_to(generated_root).as_posix()
        for path in patches_root.rglob("*.patch")
        if path.is_file()
        and path.name not in {"llm-proposed.patch", "proposed.patch"}
    )


def _apply_patch_file(*, patch_path: Path, workspace: Path) -> dict[str, object] | None:
    attempts = [
        ("git apply", ["git", "apply", "--inaccurate-eof", str(patch_path.resolve())]),
        ("patch", ["patch", "-p1", "-N", "-i", str(patch_path.resolve())]),
    ]
    errors: list[dict[str, str]] = []
    for tool_name, command in attempts:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return None
        errors.append(
            {
                "tool": tool_name,
                "message": (result.stderr or result.stdout or "unknown error").strip() or "unknown error",
            }
        )

    messages = [error["message"] for error in errors if error["message"]]
    return {
        "tool": errors[-1]["tool"] if errors else "unknown",
        "error": "\n".join(messages) or "unknown error",
        "attempts": errors,
        "target_files": _extract_patch_target_files(patch_path),
    }


def _filter_redundant_patch_artifacts(
    patch_artifacts: list[str],
    *,
    has_direct_edit_artifacts: bool = False,
) -> list[str]:
    skipped: list[str] = []
    if "patches/proposed.patch" in patch_artifacts and "patches/frontend_widget_mount.patch" in patch_artifacts:
        skipped.append("patches/frontend_widget_mount.patch")
    if "patches/proposed.patch" in patch_artifacts and "patches/backend_chat_auth_route.patch" in patch_artifacts:
        skipped.append("patches/backend_chat_auth_route.patch")
    if has_direct_edit_artifacts and "patches/frontend_widget_mount.patch" in patch_artifacts:
        skipped.append("patches/frontend_widget_mount.patch")
    if has_direct_edit_artifacts and "patches/backend_chat_auth_route.patch" in patch_artifacts:
        skipped.append("patches/backend_chat_auth_route.patch")
    return skipped


def _extract_patch_target_files(patch_path: Path) -> list[str]:
    content = patch_path.read_text(encoding="utf-8")
    targets: list[str] = []
    for match in re.finditer(r"^\+\+\+ b/(.+)$", content, re.MULTILINE):
        targets.append(match.group(1))
    return targets
