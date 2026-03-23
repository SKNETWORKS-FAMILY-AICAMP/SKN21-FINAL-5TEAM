from __future__ import annotations

import re


def build_failure_signature(*, check_name: str, summary: str) -> str:
    raw = f"{check_name}:{summary}".lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return normalized or f"{check_name}_failed"
