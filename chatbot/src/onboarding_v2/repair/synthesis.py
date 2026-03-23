from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.repair import FailureBundle

_MAX_SAMPLE_BYTES = 20_000
_MAX_SAMPLE_LINES = 400


def collect_file_samples(
    *,
    workspace_root: str | Path | None,
    related_files: list[str],
) -> list[dict[str, str]]:
    root = None if workspace_root is None else Path(workspace_root)
    samples: list[dict[str, str]] = []
    for relative_path in related_files[:5]:
        if root is None:
            break
        candidate = root / relative_path
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
    return samples


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
    return FailureBundle(
        failed_stage=failed_stage,
        failure_signature=failure_signature,
        failure_summary=failure_summary,
        trigger_event_id=trigger_event_id,
        related_artifacts=list(related_artifacts),
        related_files=list(related_files),
        related_file_samples=collect_file_samples(
            workspace_root=workspace_root,
            related_files=related_files,
        ),
        input_artifact_versions=dict(input_artifact_versions),
        attempt_number=attempt_number,
        repeat_count=repeat_count,
    )
