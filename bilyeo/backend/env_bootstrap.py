from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_ENV_LOADED = False


def ensure_backend_env_loaded() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    backend_root = Path(__file__).resolve().parent
    host_root = backend_root.parent
    for path in (host_root / ".env", backend_root / ".env"):
        if path.exists():
            load_dotenv(path, override=False)

    _ENV_LOADED = True
