from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    metadata: dict[str, Any]

    def to_hash(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
        }


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    run_id: str
    payload: dict[str, Any]

    def to_hash(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "payload": json.dumps(self.payload, ensure_ascii=False),
        }


@dataclass(frozen=True)
class RunEventRecord:
    run_id: str
    event: str
    payload: dict[str, Any]

    def to_payload(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "event": self.event,
                "payload": self.payload,
            },
            ensure_ascii=False,
        )
