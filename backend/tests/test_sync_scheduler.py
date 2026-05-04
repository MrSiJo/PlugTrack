"""Tests for adaptive cadence scheduler."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from plugtrack.plugins.pycupra.models import VehicleState
from plugtrack.services.sync_orchestrator import CarSyncState
from plugtrack.services.sync_scheduler import (
    SyncScheduler,
    compute_next_interval_seconds,
)


_DEFAULT_SETTINGS = {
    "sync_interval_minutes_idle": "30",
    "sync_interval_minutes_plugged": "10",
    "sync_interval_minutes_charging": "5",
    "sync_enabled": "true",
}


def _vehicle(charging_time_left: Optional[int]) -> VehicleState:
    return VehicleState(
        battery_level=50,
        charging=True,
        charging_state=True,
        charging_state_raw="charging",
        charging_power=7.0,
        charging_time_left=charging_time_left,
        target_soc=80,
        charging_cable_connected=True,
        charging_cable_locked=True,
        external_power=True,
        energy_flow="charging",
        vehicle_online=True,
        last_connected=datetime(2026, 5, 4, 12, tzinfo=timezone.utc),
        distance_km=12345,
        electric_range_km=200,
        position=None,
        car_captured_timestamp=datetime(2026, 5, 4, 12, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Cadence band selection
# ---------------------------------------------------------------------------


def test_idle_uses_idle_band() -> None:
    state = CarSyncState(last_state="IDLE")
    seconds = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert seconds == 30 * 60


def test_plugged_in_uses_plugged_band() -> None:
    state = CarSyncState(last_state="PLUGGED_IN")
    seconds = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert seconds == 10 * 60


def test_charging_done_uses_plugged_band() -> None:
    state = CarSyncState(last_state="CHARGING_DONE")
    seconds = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert seconds == 10 * 60


def test_charging_uses_charging_band_when_no_ttl() -> None:
    state = CarSyncState(last_state="CHARGING")
    tel = _vehicle(charging_time_left=None)
    seconds = compute_next_interval_seconds(state, tel, _DEFAULT_SETTINGS)
    assert seconds == 5 * 60


def test_charging_ttl_ceiling_clips_band() -> None:
    """charging_time_left=2min with 5min interval → 3min wait (ttl+1)."""
    state = CarSyncState(last_state="CHARGING")
    tel = _vehicle(charging_time_left=2)
    seconds = compute_next_interval_seconds(state, tel, _DEFAULT_SETTINGS)
    assert seconds == 3 * 60


def test_charging_ttl_above_ceiling_uses_ceiling() -> None:
    """charging_time_left=20min with 5min ceiling → still 5min (don't extend)."""
    state = CarSyncState(last_state="CHARGING")
    tel = _vehicle(charging_time_left=20)
    seconds = compute_next_interval_seconds(state, tel, _DEFAULT_SETTINGS)
    assert seconds == 5 * 60


# ---------------------------------------------------------------------------
# Just-transitioned override
# ---------------------------------------------------------------------------


def test_just_transitioned_returns_30_seconds() -> None:
    state = CarSyncState(last_state="CHARGING")
    seconds = compute_next_interval_seconds(
        state, None, _DEFAULT_SETTINGS, just_transitioned=True
    )
    assert seconds == 30


def test_post_transition_call_returns_to_band() -> None:
    state = CarSyncState(last_state="CHARGING")
    seconds = compute_next_interval_seconds(
        state, None, _DEFAULT_SETTINGS, just_transitioned=False
    )
    assert seconds == 5 * 60


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


def test_backoff_doubles_on_each_failure() -> None:
    # Use the CHARGING band (5min = 300s base) so two doublings stay below
    # the 60-min cap.
    state = CarSyncState(last_state="CHARGING", consecutive_failures=1)
    one_failure = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    state.consecutive_failures = 2
    two_failures = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert one_failure == 600  # 5 * 60 * 2 ** 1
    assert two_failures == 1200  # 5 * 60 * 2 ** 2
    assert two_failures == 2 * one_failure


def test_backoff_capped_at_60_minutes() -> None:
    state = CarSyncState(last_state="IDLE", consecutive_failures=12)
    seconds = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert seconds == 60 * 60


def test_backoff_resets_on_success() -> None:
    """consecutive_failures back to 0 → band interval, no backoff."""
    state = CarSyncState(last_state="PLUGGED_IN", consecutive_failures=0)
    seconds = compute_next_interval_seconds(state, None, _DEFAULT_SETTINGS)
    assert seconds == 10 * 60


# ---------------------------------------------------------------------------
# Scheduler lifecycle + sync_enabled flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_disabled_when_sync_enabled_false() -> None:
    settings = {**_DEFAULT_SETTINGS, "sync_enabled": "false"}

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(sync_callback=cb, settings_provider=lambda: settings)
    sched.start()
    try:
        assert sched.is_enabled() is False
        assert sched.is_running() is False
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_scheduler_starts_when_enabled() -> None:
    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb, settings_provider=lambda: _DEFAULT_SETTINGS
    )
    sched.start()
    try:
        assert sched.is_enabled() is True
        assert sched.is_running() is True

        state = CarSyncState(last_state="IDLE")
        seconds = sched.schedule_next(7, state, None, _DEFAULT_SETTINGS)
        assert seconds == 30 * 60
        assert state.next_poll_at is not None
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_schedule_next_no_op_when_disabled_returns_seconds() -> None:
    settings = {**_DEFAULT_SETTINGS, "sync_enabled": "false"}

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(sync_callback=cb, settings_provider=lambda: settings)
    sched.start()
    state = CarSyncState(last_state="CHARGING")
    seconds = sched.schedule_next(1, state, _vehicle(None), settings)
    # Returns the computed seconds even though no APScheduler job is added.
    assert seconds == 5 * 60
    # next_poll_at still annotated (UI uses this to show ETA).
    assert state.next_poll_at is not None


def test_invalid_setting_falls_back_to_default() -> None:
    settings = {
        "sync_interval_minutes_idle": "not-a-number",
        "sync_interval_minutes_plugged": "10",
        "sync_interval_minutes_charging": "5",
    }
    state = CarSyncState(last_state="IDLE")
    seconds = compute_next_interval_seconds(state, None, settings)
    assert seconds == 30 * 60  # fallback default


def test_negative_setting_falls_back_to_default() -> None:
    settings = {
        "sync_interval_minutes_idle": "30",
        "sync_interval_minutes_plugged": "-5",
        "sync_interval_minutes_charging": "5",
    }
    state = CarSyncState(last_state="PLUGGED_IN")
    seconds = compute_next_interval_seconds(state, None, settings)
    assert seconds == 10 * 60  # default
