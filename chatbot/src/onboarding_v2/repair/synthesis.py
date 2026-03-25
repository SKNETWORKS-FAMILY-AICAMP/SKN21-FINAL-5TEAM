from __future__ import annotations

import json
from pathlib import Path

from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.repair import FailureBundle

_MAX_SAMPLE_BYTES = 20_000
_MAX_SAMPLE_LINES = 400
_COMPILE_PREFLIGHT_CONTEXT_PATH = "__failure_context__/compile-preflight.json"


def collect_file_samples(
    *,
    workspace_root: str | Path | None,
    related_files: list[str],
) -> list[dict[str, str]]:
    root = None if workspace_root is None else Path(workspace_root).resolve()
    samples: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw_path in related_files[:5]:
        if root is None:
            break
        normalized_path = str(raw_path or "").strip()
        if not normalized_path:
            continue
        requested_path = Path(normalized_path)
        if requested_path.is_absolute():
            continue
        candidate = (root / requested_path).resolve()
        try:
            relative_path = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative_path in seen_paths:
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        truncated = "\n".join(content.splitlines()[:_MAX_SAMPLE_LINES])
        if len(truncated.encode("utf-8")) > _MAX_SAMPLE_BYTES:
            truncated = truncated.encode("utf-8")[:_MAX_SAMPLE_BYTES].decode("utf-8", errors="ignore")
        samples.append({"path": relative_path, "content": truncated})
        seen_paths.add(relative_path)
    return samples


def _is_compile_preflight_failure(
    *,
    failed_stage: str,
    failure_signature: str,
    failure_summary: str,
    related_artifacts: list[ArtifactRef],
) -> bool:
    if failed_stage != "compile":
        return False
    artifact_types = {artifact.artifact_type for artifact in related_artifacts}
    if "compile-preflight" in artifact_types:
        return True
    haystack = f"{failure_signature}\n{failure_summary}".lower()
    return "chatbot_runtime_import" in haystack or "banned import" in haystack


def _build_related_files(
    *,
    failed_stage: str,
    failure_signature: str,
    failure_summary: str,
    related_artifacts: list[ArtifactRef],
    related_files: list[str],
) -> list[str]:
    ordered: list[str] = []
    if _is_compile_preflight_failure(
        failed_stage=failed_stage,
        failure_signature=failure_signature,
        failure_summary=failure_summary,
        related_artifacts=related_artifacts,
    ):
        ordered.append("server_fastapi.py")
    for path in related_files:
        normalized = str(path or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _build_context_samples(
    *,
    failed_stage: str,
    failure_signature: str,
    failure_summary: str,
    related_artifacts: list[ArtifactRef],
    related_files: list[str],
    input_artifact_versions: dict[str, int],
) -> list[dict[str, str]]:
    if not _is_compile_preflight_failure(
        failed_stage=failed_stage,
        failure_signature=failure_signature,
        failure_summary=failure_summary,
        related_artifacts=related_artifacts,
    ):
        return []
    payload = {
        "failed_stage": failed_stage,
        "failure_signature": failure_signature,
        "failure_summary": failure_summary,
        "related_artifact_types": [artifact.artifact_type for artifact in related_artifacts],
        "related_files": related_files,
        "input_artifact_versions": input_artifact_versions,
    }
    return [
        {
            "path": _COMPILE_PREFLIGHT_CONTEXT_PATH,
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        }
    ]


def synthesize_failure(
    *,
    failed_stage: str,
    failure_signature: str,
    failure_summary: str,
    trigger_event_id: str,
    related_artifacts: list[ArtifactRef],
    related_files: list[str],
    workspace_root: str | Path | None,
    input_artifact_versions: dict[str, int],
    attempt_number: int,
    repeat_count: int,
) -> FailureBundle:
    normalized_related_files = _build_related_files(
        failed_stage=failed_stage,
        failure_signature=failure_signature,
        failure_summary=failure_summary,
        related_artifacts=related_artifacts,
        related_files=related_files,
    )
    related_file_samples = collect_file_samples(
        workspace_root=workspace_root,
        related_files=normalized_related_files,
    )
    related_file_samples.extend(
        _build_context_samples(
            failed_stage=failed_stage,
            failure_signature=failure_signature,
            failure_summary=failure_summary,
            related_artifacts=related_artifacts,
            related_files=normalized_related_files,
            input_artifact_versions=input_artifact_versions,
        )
    )
    return FailureBundle(
        failed_stage=failed_stage,
        failure_signature=failure_signature,
        failure_summary=failure_summary,
        trigger_event_id=trigger_event_id,
        related_artifacts=list(related_artifacts),
        related_files=normalized_related_files,
        related_file_samples=related_file_samples,
        input_artifact_versions=dict(input_artifact_versions),
        attempt_number=attempt_number,
        repeat_count=repeat_count,
    )
