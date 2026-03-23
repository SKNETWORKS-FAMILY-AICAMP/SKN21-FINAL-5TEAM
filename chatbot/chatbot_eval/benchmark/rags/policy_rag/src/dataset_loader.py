"""Policy RAG 평가 데이터 로더."""

from pathlib import Path
import json


def load_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows
