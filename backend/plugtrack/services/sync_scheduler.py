"""Adaptive cadence scheduler.

Wraps APScheduler `AsyncIOScheduler`. One job per active car, with the
next interval recomputed after each run based on observed state per
spec §3.6 cadence table:

| State                         | Next poll                              |
|-------------------------------|----------------------------------------|
| IDLE                          | sync_interval_minutes_idle             |
| PLUGGED_IN / CHARGING_DONE    | sync_interval_minutes_plugged          |
| CHARGING                      | min(charging_interval, charging_time_left + 1) |
| Just-transitioned             | 30s one-shot, then back to band        |
| Auth/network error            | exponential backoff capped at 60min    |

Disabled entirely when sync_enabled=false → start() is a no-op.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone

from ..plugins.pycupra.models import VehicleState
from .sync_orchestrator import CarSyncState


_TRANSITION_FOLLOWUP_SECONDS = 30
_BACKOFF_CAP_SECONDS = 60 * 60  # 1 hour
_DEFAULT_INTERVALS_MINUTES = {
    "idle": 30,
    "plugged": 10,
    "charging": 5,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _interval_seconds(settings: dict, key: str, default_minutes: int) -> int:
    raw = settings.get(f"sync_interval_minutes_{key}")
    try:
        minutes = int(raw) if raw is not None else default_minutes
    except (TypeError, ValueError):
        minutes = default_minutes
    if minutes < 1:
        minutes = default_minutes
    return minutes * 60


def compute_next_interval_seconds(
    state: CarSyncState,
    telemetry: Optional[VehicleState],
    settings: dict,
    *,
    just_transitioned: bool = False,
) -> int:
    """Pure function: return seconds until next poll for this car.

    Inputs:
    - `state` — current per-car cached state (post-poll).
    - `telemetry` — most recent telemetry, used for charging_time_left.
    - `settings` — flat dict of catalogue values.
    - `just_transitioned` — True if the latest poll changed `last_state`,
      schedules the 30-second follow-up.
    """
    # Backoff overrides everything when the car is in failure mode.
    if state.consecutive_failures > 0:
        # base = the band interval for the current state.
        base = _band_seconds(state, telemetry, settings)
        backoff = base * (2 ** state.consecutive_failures)
        return min(_BACKOFF_CAP_SECONDS, backoff)

    if just_transitioned:
        return _TRANSITION_FOLLOWUP_SECONDS

    return _band_seconds(state, telemetry, settings)


def _band_seconds(
    state: CarSyncState,
    telemetry: Optional[VehicleState],
    settings: dict,
) -> int:
    s = state.last_state
    if s == "IDLE":
        return _interval_seconds(settings, "idle", _DEFAULT_INTERVALS_MINUTES["idle"])
    if s in {"PLUGGED_IN", "CHARGING_DONE"}:
        return _interval_seconds(
            settings, "plugged", _DEFAULT_INTERVALS_MINUTES["plugged"]
        )
    if s == "CHARGING":
        ceiling = _interval_seconds(
            settings, "charging", _DEFAULT_INTERVALS_MINUTES["charging"]
        )
        if telemetry is not None and telemetry.charging_time_left:
            ttl_seconds = (telemetry.charging_time_left + 1) * 60
            if ttl_seconds < ceiling:
                return ttl_seconds
        return ceiling
    # Unknown state — fall back to idle band.
    return _interval_seconds(settings, "idle", _DEFAULT_INTERVALS_MINUTES["idle"])


SyncCallback = Callable[[int], Awaitable[Any]]


class SyncScheduler:
    """APScheduler wrapper — one DateTrigger job per car, re-armed after each run."""

    def __init__(
        self,
        sync_callback: SyncCallback,
        settings_provider: Callable[[], dict],
    ) -> None:
        self._sync_callback = sync_callback
        self._settings_provider = settings_provider
        self._scheduler: Optional[AsyncIOScheduler] = None
        # car_id → APScheduler job id (so we can replace on each run).
        self._job_ids: dict[int, str] = {}
        self._enabled = True

    def is_enabled(self) -> bool:
        return self._enabled

    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        settings = self._settings_provider()
        if not _bool_setting(settings.get("sync_enabled"), default=True):
            self._enabled = False
            return
        self._enabled = True
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def schedule_next(
        self,
        car_id: int,
        state: CarSyncState,
        telemetry: Optional[VehicleState],
        settings: dict,
        *,
        just_transitioned: bool = False,
    ) -> int:
        """Compute + apply the next interval. Returns seconds chosen.

        When `state.auth_invalid` is True (Phase 5.4) no APScheduler job
        is armed — the scheduler refuses to spin further requests at
        invalid credentials. The user must re-save cupra_* settings to
        clear the flag (which also triggers an immediate sync from the
        settings route). `next_poll_at` is left unset so the snapshot
        UI shows "—" rather than a misleading future timestamp.
        """
        if state.auth_invalid:
            self._cancel_job(car_id)
            state.next_poll_at = None
            return 0

        seconds = compute_next_interval_seconds(
            state, telemetry, settings, just_transitioned=just_transitioned
        )
        run_at = _utcnow() + timedelta(seconds=seconds)
        state.next_poll_at = run_at

        if not self._enabled or self._scheduler is None or not self._scheduler.running:
            return seconds

        job_id = f"sync-car-{car_id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        self._scheduler.add_job(
            self._sync_callback,
            trigger=DateTrigger(run_date=run_at),
            args=[car_id],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=60,
        )
        self._job_ids[car_id] = job_id
        return seconds

    def _cancel_job(self, car_id: int) -> None:
        """Remove any scheduled job for this car (best-effort)."""
        if self._scheduler is None or not self._scheduler.running:
            return
        job_id = f"sync-car-{car_id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        self._job_ids.pop(car_id, None)


def _bool_setting(raw: Any, *, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    return bool(raw)
