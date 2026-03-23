from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chatbot.src.onboarding_v2.models.common import ArtifactEnvelope, ArtifactRef


STAGE_DIRECTORY_MAP = {
    "analysis": "01-analysis",
    "planning": "02-planning",
    "compile": "03-compile",
    "apply": "04-apply",
    "validation": "05-validation",
    "export": "06-export",
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ArtifactStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.artifacts_root = self.run_root / "artifacts"
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        for stage_directory in STAGE_DIRECTORY_MAP.values():
            (self.artifacts_root / stage_directory).mkdir(parents=True, exist_ok=True)

    def write_json_artifact(
        self,
        *,
        stage: str,
        artifact_type: str,
        payload: dict[str, Any],
        producer: str,
        input_artifact_refs: list[ArtifactRef] | None = None,
        event_ref: str | None = None,
        status: str = "completed",
        provenance: dict[str, Any] | None = None,
        attempt: int = 1,
    ) -> ArtifactRef:
        artifact_dir = self._artifact_type_dir(stage=stage, artifact_type=artifact_type)
        version = self._next_version(artifact_dir)
        artifact_ref = self._build_ref(
            stage=stage,
            artifact_type=artifact_type,
            version=version,
            path=self._versioned_filename(version, suffix=".json"),
            content_hash="",
        )
        envelope = ArtifactEnvelope(
            artifact_id=f"{stage}:{artifact_type}:v{version:04d}",
            artifact_type=artifact_type,
            stage=stage,
            version=version,
            created_at=_utcnow(),
            producer=producer,
            attempt=attempt,
            input_artifact_refs=list(input_artifact_refs or []),
            event_ref=event_ref,
            status=status,
            provenance=dict(provenance or {}),
            payload=payload,
        )
        content = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2)
        artifact_ref.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = artifact_dir / artifact_ref.path
        path.write_text(content, encoding="utf-8")
        self._update_index(stage=stage, artifact_type=artifact_type, artifact_ref=artifact_ref)
        return artifact_ref

    def write_text_artifact(
        self,
        *,
        stage: str,
        artifact_type: str,
        content: str,
        suffix: str,
    ) -> ArtifactRef:
        artifact_dir = self._artifact_type_dir(stage=stage, artifact_type=artifact_type)
        version = self._next_version(artifact_dir)
        artifact_ref = self._build_ref(
            stage=stage,
            artifact_type=artifact_type,
            version=version,
            path=self._versioned_filename(version, suffix=suffix),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        path = artifact_dir / artifact_ref.path
        path.write_text(content, encoding="utf-8")
        self._update_index(stage=stage, artifact_type=artifact_type, artifact_ref=artifact_ref)
        return artifact_ref

    def read_latest_ref(self, *, stage: str, artifact_type: str) -> ArtifactRef | None:
        latest_path = self._artifact_type_dir(stage=stage, artifact_type=artifact_type) / "latest.json"
        if not latest_path.exists():
            return None
        return ArtifactRef.model_validate_json(latest_path.read_text(encoding="utf-8"))

    def _artifact_type_dir(self, *, stage: str, artifact_type: str) -> Path:
        stage_dir = self.artifacts_root / STAGE_DIRECTORY_MAP[stage]
        artifact_dir = stage_dir / artifact_type
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def _next_version(self, artifact_dir: Path) -> int:
        index_path = artifact_dir / "index.json"
        if not index_path.exists():
            return 1
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return int(payload.get("next_version") or 1)

    def _update_index(self, *, stage: str, artifact_type: str, artifact_ref: ArtifactRef) -> None:
        artifact_dir = self._artifact_type_dir(stage=stage, artifact_type=artifact_type)
        index_path = artifact_dir / "index.json"
        if index_path.exists():
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            payload = {"stage": stage, "artifact_type": artifact_type, "items": [], "next_version": 1}
        items = list(payload.get("items") or [])
        items.append(artifact_ref.model_dump(mode="json"))
        payload["items"] = items
        payload["next_version"] = artifact_ref.version + 1
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (artifact_dir / "latest.json").write_text(
            artifact_ref.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _build_ref(
        *,
        stage: str,
        artifact_type: str,
        version: int,
        path: str,
        content_hash: str,
    ) -> ArtifactRef:
        return ArtifactRef(
            stage=stage,
            artifact_type=artifact_type,
            version=version,
            path=path,
            content_hash=content_hash,
        )

    @staticmethod
    def _versioned_filename(version: int, *, suffix: str) -> str:
        return f"v{version:04d}{suffix}"
