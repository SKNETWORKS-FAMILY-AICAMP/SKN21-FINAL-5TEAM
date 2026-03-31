from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from chatbot.src.onboarding_v2.models.common import EventRecord


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class EventStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.events_root = self.run_root / "events"
        self.events_root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.events_root / "events.jsonl"
        self.views_root = self.run_root / "views"
        self.views_root.mkdir(parents=True, exist_ok=True)
        self.timeline_path = self.views_root / "timeline.txt"
        self._write_lock = threading.Lock()

    def write_event(self, **payload) -> EventRecord:
        record = EventRecord(
            event_id=payload.pop("event_id", uuid.uuid4().hex),
            timestamp=payload.pop("timestamp", _utcnow()),
            **payload,
        )
        with self._write_lock:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json())
                handle.write("\n")
            with self.timeline_path.open("a", encoding="utf-8") as handle:
                handle.write(self._format_timeline_line(record))
                handle.write("\n")
        return record

    def read_events(self) -> list[EventRecord]:
        if not self.events_path.exists():
            return []
        records: list[EventRecord] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(EventRecord.model_validate_json(line))
        return records

    def _format_timeline_line(self, record: EventRecord) -> str:
        return f"{record.timestamp} {record.stage} {record.event_type} {record.summary}"
