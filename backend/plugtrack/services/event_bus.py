"""In-process event bus for sync orchestration.

Singleton. Each subscriber gets its own asyncio.Queue (fan-out from the
single producer side). `subscribe(job_id)` is an async generator that
yields events until `sync.completed` / `sync.failed` arrives.

Multi-worker is out of scope for v1 (documented tripwire in main.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


_TERMINAL_EVENTS = frozenset({"sync.completed", "sync.failed"})


@dataclass
class SyncEvent:
    event: str
    data: dict
    job_id: str


class EventBus:
    """Per-job_id queue fan-out."""

    def __init__(self) -> None:
        # job_id → list of subscriber queues
        self._subscribers: dict[str, list[asyncio.Queue[SyncEvent]]] = {}
        self._lock = asyncio.Lock()
        # Once a job has emitted a terminal event we mark it as closed so
        # late subscribers don't hang forever.
        self._terminated: set[str] = set()

    async def publish(self, event: SyncEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(event.job_id, ()))
            if event.event in _TERMINAL_EVENTS:
                self._terminated.add(event.job_id)
        for queue in queues:
            await queue.put(event)

    async def subscribe(self, job_id: str) -> AsyncIterator[SyncEvent]:
        queue: asyncio.Queue[SyncEvent] = asyncio.Queue()
        async with self._lock:
            if job_id in self._terminated:
                # Job already finished — yield nothing, exit immediately.
                return
            self._subscribers.setdefault(job_id, []).append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
                if event.event in _TERMINAL_EVENTS:
                    return
        finally:
            async with self._lock:
                subs = self._subscribers.get(job_id)
                if subs is not None and queue in subs:
                    subs.remove(queue)
                if subs == []:
                    self._subscribers.pop(job_id, None)

    def subscriber_count(self, job_id: str) -> int:
        return len(self._subscribers.get(job_id, ()))


_BUS: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS


def reset_event_bus() -> None:
    """Test helper — drop the singleton so per-test state is clean."""
    global _BUS
    _BUS = None
