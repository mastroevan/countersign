"""Live pipeline trace: an in-memory event log plus an SSE stream.

Stages follow the demo script: webhook -> device discovery -> encryption check
-> WHEP session -> sampled frames -> Bedrock call (model ID, request ID,
latency) -> judgment -> the policy rule that fired. Events carry metadata only:
no image bytes, and nothing describing people or vehicles.

Pipeline code calls ``emit(stage, status, **data)``. It finds the bus and the
verification through a context variable that the service binds, so code deep
in the pipeline (including worker threads, which inherit the context) needs no
extra parameters and is a no-op when nothing is bound.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

KEEPALIVE_S = 15.0
SUBSCRIBER_QUEUE = 1000


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    ts: str
    verification_id: str | None
    stage: str
    status: str  # "started" | "ok" | "error" | "info"
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "verification_id": self.verification_id,
            "stage": self.stage,
            "status": self.status,
            "data": self.data,
        }


class Subscription:
    def __init__(self, bus: TraceBus, vid: str | None) -> None:
        self._bus = bus
        self.vid = vid
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[TraceEvent] = asyncio.Queue(SUBSCRIBER_QUEUE)
        self.lagged = False

    def _deliver(self, ev: TraceEvent) -> None:  # runs on the subscriber's loop
        if self.vid is not None and ev.verification_id != self.vid:
            return
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            self.lagged = True  # client reconnects with Last-Event-ID to replay

    async def get(self) -> TraceEvent:
        return await self._queue.get()

    def close(self) -> None:
        self._bus._unsubscribe(self)


class TraceBus:
    def __init__(self, max_events: int = 2000) -> None:
        self._events: deque[TraceEvent] = deque(maxlen=max_events)
        self._subs: list[Subscription] = []
        self._seq = 0
        self._lock = threading.Lock()

    def publish(
        self, verification_id: str | None, stage: str, status: str = "ok", **data: Any
    ) -> TraceEvent:
        """Thread-safe: pipeline stages may run in ``asyncio.to_thread`` workers."""
        with self._lock:
            self._seq += 1
            ev = TraceEvent(
                self._seq,
                datetime.now(timezone.utc).isoformat(),
                verification_id,
                stage,
                status,
                _jsonable(data),
            )
            self._events.append(ev)
            subs = list(self._subs)
        for sub in subs:
            try:
                sub._loop.call_soon_threadsafe(sub._deliver, ev)
            except RuntimeError:  # subscriber's loop already closed
                pass
        return ev

    def history(self, after_seq: int = 0, vid: str | None = None) -> list[TraceEvent]:
        with self._lock:
            return [
                e
                for e in self._events
                if e.seq > after_seq and (vid is None or e.verification_id == vid)
            ]

    def subscribe(self, vid: str | None = None) -> Subscription:
        sub = Subscription(self, vid)
        with self._lock:
            self._subs.append(sub)
        return sub

    def _unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)


_current: ContextVar[tuple[TraceBus, str] | None] = ContextVar("countersign_trace", default=None)


@contextmanager
def bind(bus: TraceBus, verification_id: str) -> Iterator[None]:
    token = _current.set((bus, verification_id))
    try:
        yield
    finally:
        _current.reset(token)


def emit(stage: str, status: str = "ok", **data: Any) -> None:
    """Record a trace event for the bound verification; no-op if none is bound."""
    cur = _current.get()
    if cur is not None:
        bus, vid = cur
        bus.publish(vid, stage, status, **data)


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(data, default=_default))
    return out


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, bytes):
        return f"<{len(o)} bytes>"  # never put image bytes in the trace
    if hasattr(o, "value"):
        return o.value
    return str(o)


def format_sse(ev: TraceEvent) -> str:
    return f"id: {ev.seq}\nevent: trace\ndata: {json.dumps(ev.as_dict())}\n\n"


async def sse_stream(
    bus: TraceBus,
    is_disconnected: Callable[[], Awaitable[bool]],
    vid: str | None = None,
    last_event_id: int = 0,
    follow: bool = True,
    keepalive_s: float = KEEPALIVE_S,
) -> AsyncIterator[str]:
    """Replay history after ``last_event_id``, then follow live events.

    Subscribes before reading history so nothing falls in the gap; events seen
    in both are sent once. If the client falls too far behind, the stream ends
    with ``event: lagged`` and the client resumes from its last id.
    """
    sub = bus.subscribe(vid)
    try:
        backlog = bus.history(last_event_id, vid)
        seen = {e.seq for e in backlog}
        yield "retry: 2000\n\n"
        for ev in backlog:
            yield format_sse(ev)
        if not follow:
            return
        while not await is_disconnected():
            try:
                ev = await asyncio.wait_for(sub.get(), keepalive_s)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if ev.seq in seen or ev.seq <= last_event_id:
                continue
            yield format_sse(ev)
            if sub.lagged:
                yield "event: lagged\ndata: {}\n\n"
                return
    finally:
        sub.close()
