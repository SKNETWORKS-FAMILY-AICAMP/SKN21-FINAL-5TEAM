from __future__ import annotations

import json
from pathlib import Path

from chatbot.src.onboarding_v2.models.common import DebugRecord


class DebugStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.debug_root = self.run_root / "debug" / "llm"
        self.debug_root.mkdir(parents=True, exist_ok=True)

    def write_record(self, *, stage: str, record: DebugRecord) -> Path:
        stage_root = self.debug_root / stage
        stage_root.mkdir(parents=True, exist_ok=True)
        path = stage_root / f"attempt-{record.attempt:04d}.json"
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
