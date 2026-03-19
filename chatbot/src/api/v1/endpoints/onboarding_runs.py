from __future__ import annotations

import asyncio
from typing import Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from chatbot.src.core.config import settings


router = APIRouter()


def _to_sse(payload: dict[str, Any]) -> bytes:
    return b"data: " + orjson.dumps(payload) + b"\n\n"


def _keepalive_comment() -> bytes:
    return b": keep-alive\n\n"


def _parse_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_onboarding_internal_token(request: Request) -> str:
    expected_token = settings.ONBOARDING_INTERNAL_API_TOKEN.strip()
    provided_token = _parse_bearer_token(request.headers.get("Authorization"))
    if not expected_token or provided_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid onboarding internal token",
        )
    return provided_token


def get_onboarding_event_store(request: Request) -> Any:
    store = getattr(request.app.state, "onboarding_event_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Onboarding event store is not configured",
        )
    return store


@router.get("/onboarding/runs/{run_id}/events")
async def stream_onboarding_run_events(
    run_id: str,
    request: Request,
    _: str = Depends(require_onboarding_internal_token),
    store: Any = Depends(get_onboarding_event_store),
) -> StreamingResponse:
    stream_key = f"onboarding:events:{run_id}"
    poll_interval = float(getattr(request.app.state, "onboarding_stream_poll_interval", 0.25))
    keepalive_interval = max(1, int(getattr(request.app.state, "onboarding_stream_keepalive_interval", 20)))
    max_idle_polls = getattr(request.app.state, "onboarding_stream_max_idle_polls", None)
    max_events = getattr(request.app.state, "onboarding_stream_max_events", None)

    async def event_generator():
        last_index = 0
        idle_polls = 0
        sent_events = 0

        existing = store.lrange(stream_key, 0, -1)
        for raw in existing:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            yield _to_sse(orjson.loads(raw))
            sent_events += 1
            if max_events is not None and sent_events >= int(max_events):
                return
        last_index = len(existing)

        while True:
            if await request.is_disconnected():
                break

            entries = store.lrange(stream_key, last_index, -1)
            if entries:
                for raw in entries:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    yield _to_sse(orjson.loads(raw))
                    last_index += 1
                    sent_events += 1
                    if max_events is not None and sent_events >= int(max_events):
                        return
                idle_polls = 0
                continue

            idle_polls += 1
            if idle_polls >= keepalive_interval:
                yield _keepalive_comment()
                idle_polls = 0
            if max_idle_polls is not None and idle_polls >= int(max_idle_polls):
                break
            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
