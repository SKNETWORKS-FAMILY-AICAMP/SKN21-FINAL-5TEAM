from __future__ import annotations

import shutil
import subprocess
import re
from pathlib import Path

from chatbot.src.onboarding.exporter import IGNORED_EXPORT_PARTS
from chatbot.src.onboarding.onboarding_ignore import runtime_copy_ignored_names
from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.validation import ReplayResult
from chatbot.src.onboarding_v2.storage import ArtifactStore
from chatbot.src.onboarding_v2.validation.replay_evaluator import (
    evaluate_backend_workspace_static,
    evaluate_frontend_workspace_static,
    evaluate_selected_python_targets,
)


def export_and_replay(
    *,
    host_source_root: str | Path,
    chatbot_source_root: str | Path,
    host_baseline_root: str | Path,
    chatbot_baseline_root: str | Path,
    host_runtime_workspace: str | Path,
    chatbot_runtime_workspace: str | Path,
    host_allowed_targets: set[str] | list[str] | None,
    chatbot_allowed_targets: set[str] | list[str] | None,
    runtime_root: str | Path,
    run_root: str | Path,
    site: str,
    run_id: str,
    artifact_store: ArtifactStore,
) -> tuple[ArtifactRef, ReplayResult, ArtifactRef]:
    host_source_root = Path(host_source_root)
    chatbot_source_root = Path(chatbot_source_root)
    host_baseline_root = Path(host_baseline_root)
    chatbot_baseline_root = Path(chatbot_baseline_root)
    host_runtime_workspace = Path(host_runtime_workspace)
    chatbot_runtime_workspace = Path(chatbot_runtime_workspace)
    runtime_root = Path(runtime_root)
    run_root = Path(run_root)
    host_allowed_targets = _normalize_allowed_targets(host_allowed_targets)
    chatbot_allowed_targets = _normalize_allowed_targets(chatbot_allowed_targets)

    host_patch_content = _generate_patch_content(
        baseline_root=host_baseline_root,
        runtime_workspace=host_runtime_workspace,
        allowed_targets=host_allowed_targets,
    )
    chatbot_patch_content = _generate_patch_content(
        baseline_root=chatbot_baseline_root,
        runtime_workspace=chatbot_runtime_workspace,
        allowed_targets=chatbot_allowed_targets,
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
    shutil.copytree(host_baseline_root, host_replay_workspace, ignore=_ignore_runtime_copy_directory)
    shutil.copytree(chatbot_baseline_root, chatbot_replay_workspace, ignore=_ignore_runtime_copy_directory)

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
    mismatched_targets = _collect_mismatched_targets(
        host_runtime_workspace=host_runtime_workspace,
        chatbot_runtime_workspace=chatbot_runtime_workspace,
        host_replay_workspace=host_replay_workspace,
        chatbot_replay_workspace=chatbot_replay_workspace,
        host_allowed_targets=host_allowed_targets,
        chatbot_allowed_targets=chatbot_allowed_targets,
    )
    static_validation = _evaluate_replay_static(
        host_replay_workspace=host_replay_workspace,
        chatbot_replay_workspace=chatbot_replay_workspace,
        chatbot_allowed_targets=chatbot_allowed_targets,
    )
    target_match_passed = not mismatched_targets
    static_validation_passed = bool(static_validation["passed"])
    replay_passed = (
        not failed_patch_artifacts
        and target_match_passed
        and static_validation_passed
    )

    replay_result = ReplayResult(
        replay_workspace_path=str(replay_root),
        host_replay_workspace_path=str(host_replay_workspace),
        chatbot_replay_workspace_path=str(chatbot_replay_workspace),
        host_patch_path=str(host_patch_path),
        chatbot_patch_path=str(chatbot_patch_path),
        host_baseline_root=str(host_baseline_root),
        chatbot_baseline_root=str(chatbot_baseline_root),
        passed=replay_passed,
        target_match_passed=target_match_passed,
        static_validation_passed=static_validation_passed,
        mismatched_targets=mismatched_targets,
        static_validation_summary=str(static_validation["failure_summary"] or ""),
        host_allowed_targets=sorted(host_allowed_targets),
        chatbot_allowed_targets=sorted(chatbot_allowed_targets),
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
            "target_match_passed": replay_result.target_match_passed,
            "static_validation_passed": replay_result.static_validation_passed,
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


def _generate_patch_content(
    *,
    baseline_root: Path,
    runtime_workspace: Path,
    allowed_targets: set[str] | None = None,
) -> str:
    patch_chunks: list[str] = []
    relative_paths = _collect_relative_paths(
        baseline_root=baseline_root,
        runtime_workspace=runtime_workspace,
        allowed_targets=allowed_targets,
    )
    for relative_path in relative_paths:
        relative = Path(relative_path)
        if any(part in IGNORED_EXPORT_PARTS for part in relative.parts):
            continue
        source_file = baseline_root / relative
        runtime_file = runtime_workspace / relative
        if _read_text_lines(source_file) == _read_text_lines(runtime_file):
            continue
        patch_chunks.append(
            _generate_patch_chunk(
                relative_path=relative_path,
                source_file=source_file,
                runtime_file=runtime_file,
            )
        )
    return "".join(patch_chunks)


def _read_text_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return []


def _collect_relative_paths(
    *,
    baseline_root: Path,
    runtime_workspace: Path,
    allowed_targets: set[str] | None,
) -> list[str]:
    if allowed_targets is not None:
        return sorted(allowed_targets)
    runtime_paths = {
        path.relative_to(runtime_workspace).as_posix()
        for path in runtime_workspace.rglob("*")
        if path.is_file()
    }
    baseline_paths = {
        path.relative_to(baseline_root).as_posix()
        for path in baseline_root.rglob("*")
        if path.is_file()
    }
    return sorted(runtime_paths | baseline_paths)


def _normalize_allowed_targets(targets: set[str] | list[str] | None) -> set[str]:
    if not targets:
        return set()
    return {
        str(target).strip()
        for target in targets
        if str(target).strip()
    }


def _ignore_runtime_copy_directory(_: str, names: list[str]) -> set[str]:
    return runtime_copy_ignored_names(_, names)


def _generate_patch_chunk(
    *,
    relative_path: str,
    source_file: Path,
    runtime_file: Path,
) -> str:
    result = subprocess.run(
        [
            "diff",
            "-u",
            "-N",
            "--label",
            f"a/{relative_path}",
            "--label",
            f"b/{relative_path}",
            str(source_file),
            str(runtime_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode in {0, 1} and result.stdout:
        return result.stdout
    if result.returncode == 0:
        return ""
    source_lines = _read_text_lines(source_file)
    runtime_lines = _read_text_lines(runtime_file)
    import difflib

    return "".join(
        difflib.unified_diff(
            source_lines,
            runtime_lines,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )


def _apply_patch_file(*, patch_path: Path, workspace: Path) -> dict[str, object] | None:
    attempts = [
        ("patch", ["patch", "-p1", "-N", "-i", str(patch_path.resolve())]),
        ("git apply", ["git", "apply", "--inaccurate-eof", str(patch_path.resolve())]),
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
    return {
        "tool": errors[-1]["tool"] if errors else "unknown",
        "error": "\n".join(error["message"] for error in errors if error["message"]) or "unknown error",
        "attempts": errors,
        "target_files": _extract_patch_target_files(patch_path),
    }


def _extract_patch_target_files(patch_path: Path) -> list[str]:
    content = patch_path.read_text(encoding="utf-8")
    return [match.group(1) for match in re.finditer(r"^\+\+\+ b/(.+)$", content, re.MULTILINE)]


def _collect_mismatched_targets(
    *,
    host_runtime_workspace: Path,
    chatbot_runtime_workspace: Path,
    host_replay_workspace: Path,
    chatbot_replay_workspace: Path,
    host_allowed_targets: set[str],
    chatbot_allowed_targets: set[str],
) -> list[str]:
    mismatches: list[str] = []
    mismatches.extend(
        _compare_allowed_targets(
            scope="host",
            runtime_workspace=host_runtime_workspace,
            replay_workspace=host_replay_workspace,
            allowed_targets=host_allowed_targets,
        )
    )
    mismatches.extend(
        _compare_allowed_targets(
            scope="chatbot",
            runtime_workspace=chatbot_runtime_workspace,
            replay_workspace=chatbot_replay_workspace,
            allowed_targets=chatbot_allowed_targets,
        )
    )
    return sorted(mismatches)


def _compare_allowed_targets(
    *,
    scope: str,
    runtime_workspace: Path,
    replay_workspace: Path,
    allowed_targets: set[str],
) -> list[str]:
    mismatches: list[str] = []
    for relative_path in sorted(allowed_targets):
        runtime_file = runtime_workspace / relative_path
        replay_file = replay_workspace / relative_path
        runtime_exists = runtime_file.exists()
        replay_exists = replay_file.exists()
        if runtime_exists != replay_exists:
            mismatches.append(f"{scope}:{relative_path}")
            continue
        if not runtime_exists and not replay_exists:
            continue
        try:
            runtime_bytes = runtime_file.read_bytes()
            replay_bytes = replay_file.read_bytes()
        except OSError:
            mismatches.append(f"{scope}:{relative_path}")
            continue
        if runtime_bytes != replay_bytes:
            mismatches.append(f"{scope}:{relative_path}")
    return mismatches


def _evaluate_replay_static(
    *,
    host_replay_workspace: Path,
    chatbot_replay_workspace: Path,
    chatbot_allowed_targets: set[str],
) -> dict[str, object]:
    host_backend = evaluate_backend_workspace_static(host_replay_workspace)
    host_frontend = evaluate_frontend_workspace_static(host_replay_workspace)
    chatbot_python = evaluate_selected_python_targets(
        chatbot_replay_workspace,
        chatbot_allowed_targets,
    )
    passed = (
        bool(host_backend["passed"])
        and bool(host_frontend["passed"])
        and bool(chatbot_python["passed"])
    )
    if not host_backend["passed"]:
        failure_summary = str(host_backend["failure_summary"])
    elif not host_frontend["passed"]:
        failure_summary = str(host_frontend["failure_summary"])
    elif not chatbot_python["passed"]:
        failure_summary = str(chatbot_python["failure_summary"])
    else:
        failure_summary = "replay static validation passed"
    return {
        "passed": passed,
        "failure_summary": failure_summary,
        "host_backend": host_backend,
        "host_frontend": host_frontend,
        "chatbot_python": chatbot_python,
    }
