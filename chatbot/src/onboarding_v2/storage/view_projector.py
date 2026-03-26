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
        retrieval_status: dict[str, dict[str, object]] | None = None,
        final_capability_profile: str | None = None,
        enabled_retrieval_corpora: list[str] | None = None,
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
            retrieval_status=dict(retrieval_status or {}),
            final_capability_profile=final_capability_profile,
            enabled_retrieval_corpora=list(enabled_retrieval_corpora or []),
            stages=stages,
        )
        self._write_json_view(
            name="run-summary.json",
            payload=summary.model_dump(mode="json"),
        )
        self._write_json_view(
            name="latest-stage-status.json",
            payload={
                "run_id": run_id,
                "site": site,
                "status": status,
                "latest_event_id": latest_event_id,
                "retrieval_status": dict(retrieval_status or {}),
                "final_capability_profile": final_capability_profile,
                "enabled_retrieval_corpora": list(enabled_retrieval_corpora or []),
                "stages": [stage.model_dump(mode="json") for stage in stages],
            },
        )
        self._write_timeline(events)
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

    def _write_json_view(self, *, name: str, payload: dict[str, object]) -> None:
        (self.views_root / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_timeline(self, events: list) -> None:
        lines = [
            f"{event.timestamp} {event.stage} {event.event_type} {event.summary}"
            for event in events
        ]
        (self.views_root / "timeline.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )
