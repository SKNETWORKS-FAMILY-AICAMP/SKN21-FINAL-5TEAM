from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LlmUsageStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.path = self.run_root / "debug" / "llm-usage.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        stage: str,
        phase: str,
        attempt: int,
        provider: str,
        model: str,
        usage: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Path:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "phase": phase,
            "attempt": attempt,
            "provider": provider,
            "model": model,
            "usage": dict(usage or {}),
            "extra": dict(extra or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return self.path
