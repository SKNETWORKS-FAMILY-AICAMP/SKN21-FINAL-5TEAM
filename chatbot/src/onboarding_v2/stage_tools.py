from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from chatbot.src.onboarding_v2.models.analysis import CandidateSet, WorkspaceProfile
from chatbot.src.onboarding_v2.models.common import PathCandidate
from chatbot.src.onboarding_v2.models.repair import FailureBundle

_MAX_FILE_CHARS = 12_000


@dataclass(slots=True)
class StageToolRuntime:
    stage: str
    root: Path
    allowed_paths: tuple[str, ...]
    tools: list[BaseTool]


def build_repair_tool_runtime(
    *,
    root: str | Path,
    failure_bundle: FailureBundle,
    analysis_bundle_payload: dict[str, Any],
) -> StageToolRuntime:
    root_path = Path(root).resolve()
    read_queue_paths = [
        _normalize_allowlist_path(root=root_path, path=item.get("path"))
        for item in list(analysis_bundle_payload.get("read_queue") or [])
    ]
    allowed_paths = _dedupe_sorted(
        [
            *[_normalize_allowlist_path(root=root_path, path=path) for path in failure_bundle.related_files],
            *read_queue_paths,
            _normalize_allowlist_path(root=root_path, path=".env"),
            _normalize_allowlist_path(root=root_path, path="backend/.env"),
        ]
    )
    allowed_set = set(allowed_paths)

    def list_repair_paths() -> dict[str, Any]:
        return {
            "stage": "repair",
            "paths": list(allowed_paths),
        }

    def read_repair_path(path: str) -> dict[str, Any]:
        normalized = _normalize_requested_path(root=root_path, path=path)
        if normalized is None or normalized not in allowed_set:
            return {
                "path": str(path or "").strip(),
                "error": "path_not_allowed",
            }
        return _read_path_payload(root=root_path, normalized_path=normalized)

    return StageToolRuntime(
        stage="repair",
        root=root_path,
        allowed_paths=tuple(allowed_paths),
        tools=[
            StructuredTool.from_function(
                name="list_repair_paths",
                description="List the deterministic repair file allowlist.",
                func=list_repair_paths,
            ),
            StructuredTool.from_function(
                name="read_repair_path",
                description="Read a single repair file from the deterministic allowlist.",
                func=read_repair_path,
            ),
        ],
    )


def build_analysis_tool_runtime(
    *,
    root: str | Path,
    workspace_profile: WorkspaceProfile,
    candidate_set: CandidateSet,
) -> StageToolRuntime:
    root_path = Path(root).resolve()
    category_map: dict[str, tuple[str, ...]] = {
        field_name: tuple(_candidate_paths(getattr(candidate_set, field_name)))
        for field_name in CandidateSet.model_fields
    }
    workspace_paths = _dedupe_sorted(
        [
            _normalize_allowlist_path(root=root_path, path=workspace_profile.manifest_path),
        ]
    )
    category_map["workspace"] = tuple(workspace_paths)
    allowed_paths = tuple(
        _dedupe_sorted(path for paths in category_map.values() for path in paths)
    )
    allowed_set = set(allowed_paths)

    def list_analysis_paths(category: str | None = None) -> dict[str, Any]:
        normalized_category = str(category or "").strip()
        if normalized_category:
            paths = category_map.get(normalized_category, ())
        else:
            paths = allowed_paths
        return {
            "stage": "analysis",
            "category": normalized_category or "all",
            "paths": list(paths),
        }

    def read_analysis_path(path: str) -> dict[str, Any]:
        normalized = _normalize_requested_path(root=root_path, path=path)
        if normalized is None or normalized not in allowed_set:
            return {
                "path": str(path or "").strip(),
                "error": "path_not_allowed",
            }
        return _read_path_payload(root=root_path, normalized_path=normalized)

    return StageToolRuntime(
        stage="analysis",
        root=root_path,
        allowed_paths=allowed_paths,
        tools=[
            StructuredTool.from_function(
                name="list_analysis_paths",
                description="List deterministic analysis candidate paths by category or for the whole allowlist.",
                func=list_analysis_paths,
            ),
            StructuredTool.from_function(
                name="read_analysis_path",
                description="Read a single analysis path from the deterministic allowlist.",
                func=read_analysis_path,
            ),
        ],
    )


def _candidate_paths(items: list[PathCandidate]) -> list[str]:
    return _dedupe_sorted(item.path for item in items if str(item.path or "").strip())


def _normalize_allowlist_path(*, root: Path, path: Any) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    normalized = _normalize_requested_path(root=root, path=raw)
    return normalized or ""


def _normalize_requested_path(*, root: Path, path: str) -> str | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        requested = Path(raw)
        if requested.is_absolute():
            resolved = requested.resolve()
        else:
            resolved = (root / requested).resolve()
        normalized = resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None
    return normalized


def _read_path_payload(*, root: Path, normalized_path: str) -> dict[str, Any]:
    target = root / normalized_path
    if not target.exists():
        return {
            "path": normalized_path,
            "error": "path_missing",
        }
    if target.is_dir():
        return {
            "path": normalized_path,
            "error": "path_is_directory",
        }
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "path": normalized_path,
            "error": "read_failed",
            "details": str(exc),
        }
    truncated = len(content) > _MAX_FILE_CHARS
    return {
        "path": normalized_path,
        "content": content[:_MAX_FILE_CHARS],
        "truncated": truncated,
    }


def _dedupe_sorted(values: list[str] | tuple[str, ...] | Any) -> list[str]:
    normalized: dict[str, None] = {}
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        normalized[item] = None
    return sorted(normalized)
