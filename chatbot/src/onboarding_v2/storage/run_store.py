from __future__ import annotations

import json
from pathlib import Path


class RunStore:
    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root)
        self.run_root.mkdir(parents=True, exist_ok=True)

    def write_run_metadata(
        self,
        *,
        site: str,
        source_root: str,
        run_id: str,
        agent_version: str,
        engine_version: str = "v2",
        schema_version: str = "1.0",
    ) -> Path:
        path = self.run_root / "run.json"
        payload = {
            "site": site,
            "source_root": source_root,
            "run_id": run_id,
            "engine": engine_version,
            "agent_version": agent_version,
            "schema_version": schema_version,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_manifest(
        self,
        *,
        site: str,
        source_root: str,
        run_id: str,
        credentials: dict[str, str] | None = None,
        tests: dict[str, object] | None = None,
    ) -> Path:
        path = self.run_root / "manifest.json"
        payload = {
            "site": site,
            "source_root": source_root,
            "run_id": run_id,
            "credentials": dict(credentials or {}),
        }
        if tests is not None:
            payload["tests"] = tests
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
