from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

EventCallback = Callable[[dict[str, Any]], None]
ResultT = TypeVar("ResultT")


def emit_stage_event(
    event_callback: EventCallback | None,
    *,
    phase: str,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
    **payload: Any,
) -> None:
    if event_callback is None:
        return
    event = {
        "phase": phase,
        "event_type": event_type,
        "summary": summary,
        "details": dict(details or {}),
    }
    event.update(payload)
    event_callback(event)


@dataclass(slots=True)
class ProgressHeartbeat:
    event_callback: EventCallback | None
    phase: str
    event_type: str
    summary: str
    heartbeat_interval_s: float = 5.0
    details_factory: Callable[[int], dict[str, Any]] | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    _started_at: float = field(default_factory=time.monotonic, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> "ProgressHeartbeat":
        if self.event_callback is None or self.heartbeat_interval_s <= 0:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.1, self.heartbeat_interval_s))

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)

    def _run(self) -> None:
        while not self._stop_event.wait(self.heartbeat_interval_s):
            details = {"elapsed_ms": self.elapsed_ms(), "status": "running"}
            if self.details_factory is not None:
                details.update(self.details_factory(self.elapsed_ms()))
            emit_stage_event(
                self.event_callback,
                phase=self.phase,
                event_type=self.event_type,
                summary=self.summary,
                details=details,
                **self.payload,
            )


def run_with_heartbeat(
    action: Callable[[], ResultT],
    *,
    event_callback: EventCallback | None,
    phase: str,
    started_event_type: str,
    started_summary: str,
    progress_event_type: str,
    progress_summary: str,
    completed_event_type: str,
    completed_summary: str,
    failed_event_type: str | None = None,
    failed_summary: str | None = None,
    heartbeat_interval_s: float = 5.0,
    started_details: dict[str, Any] | None = None,
    progress_details_factory: Callable[[int], dict[str, Any]] | None = None,
    completed_details_factory: Callable[[ResultT, int], dict[str, Any]] | None = None,
    failed_details_factory: Callable[[Exception, int], dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> ResultT:
    emit_stage_event(
        event_callback,
        phase=phase,
        event_type=started_event_type,
        summary=started_summary,
        details=started_details,
        **dict(payload or {}),
    )
    heartbeat = ProgressHeartbeat(
        event_callback=event_callback,
        phase=phase,
        event_type=progress_event_type,
        summary=progress_summary,
        heartbeat_interval_s=heartbeat_interval_s,
        details_factory=progress_details_factory,
        payload=dict(payload or {}),
    ).start()
    started_at = time.monotonic()
    try:
        result = action()
    except Exception as exc:
        heartbeat.stop()
        if failed_event_type is not None and failed_summary is not None:
            details = {"elapsed_ms": int((time.monotonic() - started_at) * 1000), "status": "failed"}
            if failed_details_factory is not None:
                details.update(failed_details_factory(exc, details["elapsed_ms"]))
            emit_stage_event(
                event_callback,
                phase=phase,
                event_type=failed_event_type,
                summary=failed_summary,
                details=details,
                **dict(payload or {}),
            )
        raise
    heartbeat.stop()
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    details = {"elapsed_ms": elapsed_ms, "status": "completed"}
    if completed_details_factory is not None:
        details.update(completed_details_factory(result, elapsed_ms))
    emit_stage_event(
        event_callback,
        phase=phase,
        event_type=completed_event_type,
        summary=completed_summary,
        details=details,
        **dict(payload or {}),
    )
    return result
