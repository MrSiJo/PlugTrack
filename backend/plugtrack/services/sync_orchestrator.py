"""Per-car sync orchestrator.

Coordinates a single in-process sync run per car. Per-car mutex ensures
only one sync per vehicle at a time; concurrent calls for the same car
are serialised and the second caller receives the same in-flight job
handle (idempotent force-sync).

Phase 4 task 4.1 ships the skeleton: lock+state book-keeping, idempotent
job handles. Tasks 4.2/4.3/4.4 wire in the state-machine synthesiser,
adaptive scheduler, and event-bus emission.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CarSyncState:
    """Per-car cached state — drives cadence + sub-poll-interval synthesis."""

    last_state: str = "IDLE"  # IDLE | PLUGGED_IN | CHARGING | CHARGING_DONE
    last_soc: Optional[int] = None
    last_car_captured_timestamp: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    active_job_id: Optional[str] = None


@dataclass
class SyncJob:
    """Handle returned to a sync caller."""

    job_id: str
    car_id: int
    kind: str  # 'periodic' | 'force' | 'transition_followup'
    started_at: datetime = field(default_factory=_utcnow)
    ended_at: Optional[datetime] = None
    status: str = "running"  # running | completed | failed
    error_reason: Optional[str] = None
    error_detail: Optional[str] = None
    _done_event: asyncio.Event = field(default_factory=asyncio.Event)

    def complete(self) -> None:
        if self.status == "running":
            self.status = "completed"
            self.ended_at = _utcnow()
            self._done_event.set()

    def fail(self, reason: str, detail: Optional[str] = None) -> None:
        if self.status == "running":
            self.status = "failed"
            self.error_reason = reason
            self.error_detail = detail
            self.ended_at = _utcnow()
            self._done_event.set()

    async def wait(self) -> None:
        await self._done_event.wait()


# Type alias for the pluggable poll worker. Exists so tests can inject a
# scripted state machine without spinning up the whole pycupra stack.
PollWorker = Callable[["SyncJob", CarSyncState], Awaitable[Any]]


class SyncOrchestrator:
    """Owns per-car state + locks; serialises syncs per vehicle."""

    def __init__(self, poll_worker: Optional[PollWorker] = None) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._state: dict[int, CarSyncState] = {}
        self._active_jobs: dict[int, SyncJob] = {}
        # Worker indirection: defaults to a no-op so this task is testable
        # in isolation. Phase 4.4 wiring replaces the default with the
        # full session-synthesiser + event-bus pipeline.
        self._poll_worker: PollWorker = poll_worker or self._noop_worker

    def set_poll_worker(self, worker: PollWorker) -> None:
        self._poll_worker = worker

    @staticmethod
    async def _noop_worker(job: SyncJob, state: CarSyncState) -> None:
        return None

    def _get_lock(self, car_id: int) -> asyncio.Lock:
        lock = self._locks.get(car_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[car_id] = lock
        return lock

    def get_state(self, car_id: int) -> Optional[CarSyncState]:
        return self._state.get(car_id)

    def ensure_state(self, car_id: int) -> CarSyncState:
        st = self._state.get(car_id)
        if st is None:
            st = CarSyncState()
            self._state[car_id] = st
        return st

    def active_job(self, car_id: int) -> Optional[SyncJob]:
        job = self._active_jobs.get(car_id)
        if job is None:
            return None
        if job.status != "running":
            return None
        return job

    def snapshot(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for car_id, st in self._state.items():
            out[car_id] = {
                "last_state": st.last_state,
                "last_soc": st.last_soc,
                "next_poll_at": st.next_poll_at.isoformat() if st.next_poll_at else None,
                "last_error": st.last_error,
                "active_job_id": st.active_job_id,
                "consecutive_failures": st.consecutive_failures,
            }
        return out

    async def sync_car(self, car_id: int, kind: str = "periodic") -> SyncJob:
        """Run (or attach to) a sync for `car_id`.

        - If a job is already in flight for this car, return its handle
          immediately (idempotent — the caller can subscribe to the same
          stream).
        - Otherwise acquire the per-car lock and run the poll worker.
        """
        existing = self.active_job(car_id)
        if existing is not None:
            return existing

        lock = self._get_lock(car_id)
        # Try to enter the critical section. Another caller may have
        # entered between our active_job() check and lock acquisition;
        # re-check inside.
        if lock.locked():
            # Check if there's an active job we should attach to.
            existing = self.active_job(car_id)
            if existing is not None:
                return existing

        async with lock:
            # Double-check after acquiring lock — another waiter may have
            # already started + finished a job.
            existing = self.active_job(car_id)
            if existing is not None:
                return existing

            job = SyncJob(
                job_id=uuid.uuid4().hex,
                car_id=car_id,
                kind=kind,
            )
            state = self.ensure_state(car_id)
            state.active_job_id = job.job_id
            self._active_jobs[car_id] = job

            try:
                await self._poll_worker(job, state)
                job.complete()
                state.consecutive_failures = 0
                state.last_error = None
            except Exception as exc:  # noqa: BLE001 — surface to job handle
                job.fail("worker_error", str(exc))
                state.consecutive_failures += 1
                state.last_error = str(exc)
            finally:
                state.active_job_id = None
                # Leave the job in `_active_jobs` only briefly so a
                # concurrent caller that already grabbed the handle can
                # still observe the final status. Since active_job()
                # filters by status=="running", a completed job won't be
                # re-attached to.
                # Drop the entry so the dict doesn't grow unboundedly.
                if self._active_jobs.get(car_id) is job:
                    self._active_jobs.pop(car_id, None)

            return job
