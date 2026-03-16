from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .site_analyzer import analyze_site


def generate_run_bundle(
    *,
    site: str,
    source_root: str | Path,
    generated_root: str | Path,
    run_id: str,
    agent_version: str,
) -> Path:
    source_path = Path(source_root)
    run_root = Path(generated_root) / site / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    analysis = analyze_site(source_path)

    manifest = {
        "run_id": run_id,
        "site": site,
        "source_root": str(source_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": agent_version,
        "analysis": analysis,
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }

    (run_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return run_root
