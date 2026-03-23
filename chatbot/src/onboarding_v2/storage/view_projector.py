from __future__ import annotations

import json
from pathlib import Path

from chatbot.src.onboarding_v2.models.common import ArtifactRef, RunSummaryView, StageLatestView
from chatbot.src.onboarding_v2.storage.artifact_store import STAGE_DIRECTORY_MAP
from chatbot.src.onboarding_v2.storage.event_store import EventStore


class ViewProjector:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.views_root = self.run_root / "views"
        self.views_root.mkdir(parents=True, exist_ok=True)

    def project(
        self,
        *,
        run_id: str,
        site: str,
        status: str,
        latest_failure_signature: str | None = None,
        latest_rewind_to: str | None = None,
        repair_attempt_count: int = 0,
        stopped_for_review: bool = False,
    ) -> RunSummaryView:
        stages: list[StageLatestView] = []
        for stage, stage_dir in STAGE_DIRECTORY_MAP.items():
            artifact_root = self.run_root / "artifacts" / stage_dir
            latest_ref = self._load_latest_ref(artifact_root)
            artifact_count = self._count_artifacts(artifact_root)
            stages.append(
                StageLatestView(
                    stage=stage,
                    latest_artifact=latest_ref,
                    artifact_count=artifact_count,
                )
            )

        events = EventStore(self.run_root).read_events()
        latest_event_id = events[-1].event_id if events else None
        summary = RunSummaryView(
            run_id=run_id,
            site=site,
            status=status,
            latest_failure_signature=latest_failure_signature,
            latest_rewind_to=latest_rewind_to,
            repair_attempt_count=repair_attempt_count,
            stopped_for_review=stopped_for_review,
            latest_event_id=latest_event_id,
            stages=stages,
        )
        (self.views_root / "run-summary.json").write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return summary

    def _load_latest_ref(self, artifact_root: Path) -> ArtifactRef | None:
        for latest_path in sorted(artifact_root.glob("*/latest.json")):
            return ArtifactRef.model_validate_json(latest_path.read_text(encoding="utf-8"))
        return None

    def _count_artifacts(self, artifact_root: Path) -> int:
        count = 0
        for index_path in artifact_root.glob("*/index.json"):
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            count += len(payload.get("items") or [])
        return count
