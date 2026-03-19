from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .redis_store import RedisRunJobStore


def build_onboarding_event_store(
    *,
    redis_url: str,
    client_factory: Callable[[str], Any] | None = None,
) -> RedisRunJobStore | None:
    if not redis_url.strip():
        return None

    factory = client_factory or _default_client_factory
    client = factory(redis_url)
    return RedisRunJobStore(client)


def close_onboarding_event_store(store: RedisRunJobStore | None) -> None:
    if store is None:
        return
    client = store.redis_client
    close = getattr(client, "close", None)
    if callable(close):
        close()


def _default_client_factory(redis_url: str) -> Any:
    try:
        from redis import Redis
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "redis package is required when ONBOARDING_REDIS_URL is configured"
        ) from exc
    return Redis.from_url(redis_url, decode_responses=True)
