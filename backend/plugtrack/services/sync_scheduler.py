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
| Quota stretching              | interval × stretch multiplier (1–4×)   |
| Quota paused                  | no job armed, next_poll_at = None      |

Disabled entirely when sync_enabled=false → start() is a no-op.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import date, datetime, timedelta, timezone

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


def quota_factor(
    used: int,
    budget: int,
    soft_fraction: float,
) -> tuple[str, float]:
    """Pure function: compute the quota state and interval multiplier.

    Returns ``(state, multiplier)`` where:

    - ``state`` is one of ``"ok"``, ``"stretching"``, or ``"paused"``.
    - ``multiplier`` is the factor to apply to the computed cadence
      interval.  1.0 means no change; values > 1.0 stretch (slow down)
      polling; the paused state is indicated by the state string (the
      caller must arm no job rather than multiply).

    Bands:
    - below soft threshold (used < budget * soft_fraction): ok, 1.0×
    - at or above soft threshold but below budget: stretching, 1.0–4.0×
      (linear interpolation: 1× at the soft line, 4× at the budget).
    - at or above budget: paused, 4.0× (caller honours the state, not the
      multiplier, and arms no new job).
    """
    if budget <= 0:
        # Degenerate budget — treat as no budget configured; don't pause.
        return "ok", 1.0

    soft_cap = budget * soft_fraction

    if used < soft_cap:
        return "ok", 1.0

    if used >= budget:
        return "paused", 4.0

    # Stretching: linear from 1× at soft_cap to 4× at budget.
    stretch_range = budget - soft_cap
    if stretch_range <= 0:
        return "stretching", 4.0
    progress = (used - soft_cap) / stretch_range  # 0.0 → 1.0
    multiplier = 1.0 + 3.0 * progress  # 1× → 4×
    return "stretching", multiplier


def _quota_settings(settings: dict) -> tuple[int, float]:
    """Extract budget and soft_fraction from the settings dict."""
    try:
        budget = int(settings.get("sync_daily_request_budget") or 800)
    except (TypeError, ValueError):
        budget = 800
    try:
        soft_fraction = float(settings.get("sync_quota_soft_fraction") or 0.75)
    except (TypeError, ValueError):
        soft_fraction = 0.75
    # Clamp soft_fraction to (0, 1].
    soft_fraction = max(0.01, min(1.0, soft_fraction))
    return budget, soft_fraction


SyncCallback = Callable[[int], Awaitable[Any]]


class SyncScheduler:
    """APScheduler wrapper — one DateTrigger job per car, re-armed after each run."""

    def __init__(
        self,
        sync_callback: SyncCallback,
        settings_provider: Callable[[], dict],
        quota_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        self._sync_callback = sync_callback
        self._settings_provider = settings_provider
        # Optional callable that returns today's request count from the DB.
        # When None the quota check is skipped (e.g. in existing tests that
        # don't need quota behaviour).
        self._quota_provider = quota_provider
        self._scheduler: Optional[AsyncIOScheduler] = None
        # car_id → APScheduler job id (so we can replace on each run).
        self._job_ids: dict[int, str] = {}
        self._enabled = True
        # Track the last day we saw so we can detect midnight rollover and
        # re-arm any cars that were paused by the quota.
        self._last_quota_day: Optional[date] = None
        # Set of car_ids currently paused by the quota (not auth).
        self._quota_paused_cars: set[int] = set()

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

        When ``state.auth_invalid`` is True no APScheduler job is armed —
        the scheduler refuses to spin further requests at invalid credentials.
        The user must re-save cupra_* settings to clear the flag.

        When the daily request quota is exhausted (``quota_state == "paused"``)
        no job is armed either; ``next_poll_at`` is set to None with the
        distinction that it was the quota (not bad credentials) that paused.
        Paused cars resume automatically after the local-midnight day rollover:
        the next call to ``schedule_next`` (from any car's post-sync callback)
        detects a new day, reads a zeroed count, and re-arms all quota-paused
        cars.
        """
        # ---- midnight rollover: re-arm quota-paused cars on new day ----
        self._maybe_rearm_on_new_day()

        if state.auth_invalid:
            self._cancel_job(car_id)
            state.next_poll_at = None
            return 0

        # ---- quota check ----
        quota_state_str, multiplier = self._compute_quota_factor(settings)
        if quota_state_str == "paused":
            self._cancel_job(car_id)
            state.next_poll_at = None
            self._quota_paused_cars.add(car_id)
            return 0

        # Remove from paused set if we're back under budget.
        self._quota_paused_cars.discard(car_id)

        seconds = compute_next_interval_seconds(
            state, telemetry, settings, just_transitioned=just_transitioned
        )

        # Apply quota stretch multiplier (no-op when multiplier == 1.0).
        seconds = int(seconds * multiplier)

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

    def _compute_quota_factor(self, settings: dict) -> tuple[str, float]:
        """Return (quota_state, multiplier) from today's count + settings."""
        if self._quota_provider is None:
            return "ok", 1.0
        try:
            used = self._quota_provider()
        except Exception:
            # If we can't read the count, don't block polling.
            return "ok", 1.0
        budget, soft_fraction = _quota_settings(settings)
        return quota_factor(used, budget, soft_fraction)

    def _maybe_rearm_on_new_day(self) -> None:
        """Detect a calendar-day rollover and re-arm quota-paused cars.

        Called at the top of every ``schedule_next`` invocation (which fires
        after every sync, periodic or force). When the local date changes:
        - The quota counter in the DB has a new-day row (or is 0 for today).
        - Any car paused purely by quota should be re-scheduled.
        """
        today = date.today()
        if self._last_quota_day is None:
            self._last_quota_day = today
            return

        if today <= self._last_quota_day:
            return

        # New day — update the tracker and re-arm quota-paused cars.
        self._last_quota_day = today
        cars_to_rearm = list(self._quota_paused_cars)
        self._quota_paused_cars.clear()

        if not cars_to_rearm:
            return
        if not self._enabled or self._scheduler is None or not self._scheduler.running:
            return

        # Arm each paused car for an immediate check (1-second delay so we
        # don't pile them all at the same tick).
        for i, paused_car_id in enumerate(cars_to_rearm):
            try:
                run_at = _utcnow() + timedelta(seconds=1 + i)
                job_id = f"sync-car-{paused_car_id}"
                self._scheduler.add_job(
                    self._sync_callback,
                    trigger=DateTrigger(run_date=run_at),
                    args=[paused_car_id],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=60,
                )
                self._job_ids[paused_car_id] = job_id
            except Exception:
                pass

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
