"""Phase 5.4 — auth-failure UX wiring.

Asserts:
- The worker sets `state.auth_invalid=True` on `_AuthError`.
- The scheduler refuses to arm a job while `auth_invalid` is True.
- `SyncOrchestrator.clear_auth_invalid` resets the flag + counter and
  reports which cars actually changed.
- PUT /api/settings with a `cupra_*` key triggers an immediate sync
  attempt for every car belonging to the requesting user.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio

from plugtrack.models import Car, Setting, User
from plugtrack.plugins.pycupra.models import VehicleState
from plugtrack.services.event_bus import EventBus
from plugtrack.services.sync_orchestrator import (
    CarSyncState,
    SyncJob,
    SyncOrchestrator,
)
from plugtrack.services.sync_scheduler import SyncScheduler
from plugtrack.services.sync_worker import (
    ProductionPollWorker,
    _AuthError,
)
from tests.api.conftest import csrf_headers


def _ts(offset: int = 0) -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset)


def _vehicle(soc: int = 50) -> VehicleState:
    return VehicleState(
        battery_level=soc, charging=False, charging_state=False,
        charging_state_raw="",
        charging_power=None, charging_time_left=None, target_soc=80,
        charging_cable_connected=False, charging_cable_locked=False,
        external_power=False, energy_flow=None, vehicle_online=True,
        last_connected=_ts(), distance_km=12345, electric_range_km=200,
        position=None, car_captured_timestamp=_ts(),
    )


# ---------------------------------------------------------------------------
# Worker sets the flag on auth failure
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded(test_sessionmaker):
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        car = Car(
            user_id=user.id,
            make="Cupra", model="Born", battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
            provider="cupra_connect", provider_vehicle_id="VIN-X",
        )
        session.add(car)
        session.add(
            Setting(
                key="default_home_rate_p_per_kwh",
                value="7.5", value_type="float",
                group_name="cost", label="x", description=None,
                default_value="7.5", is_secret=False,
            )
        )
        await session.commit()
        await session.refresh(car)
    return {"user_id": user.id, "car_id": car.id}


@pytest.mark.asyncio
async def test_worker_sets_auth_invalid_on_auth_error(
    seeded, test_sessionmaker
):
    bus = EventBus()
    car_id = seeded["car_id"]

    async def bad_adapter(_car: Car) -> Any:
        raise _AuthError("nope")

    async def fetcher(_conn, _vid):
        raise AssertionError("fetcher should never be reached")

    async def settings_provider(user_id: int) -> dict:
        return {}

    worker = ProductionPollWorker(
        db_sessionmaker=test_sessionmaker,
        settings_provider=settings_provider,
        adapter_provider=bad_adapter,
        bus=bus,
        vehicle_state_fetcher=fetcher,
    )

    state = CarSyncState(last_state="IDLE")
    job = SyncJob(job_id="j1", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)

    assert new_state.auth_invalid is True
    assert new_state.last_error == "credentials_invalid"
    assert new_state.consecutive_failures == 1


# ---------------------------------------------------------------------------
# Scheduler skips when auth_invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_skips_when_auth_invalid():
    callback_calls: list[int] = []

    async def callback(car_id: int) -> None:
        callback_calls.append(car_id)

    scheduler = SyncScheduler(
        sync_callback=callback,
        settings_provider=lambda: {"sync_enabled": "true"},
    )
    scheduler.start()

    state = CarSyncState(last_state="IDLE", auth_invalid=True)
    seconds = scheduler.schedule_next(
        car_id=42, state=state, telemetry=None,
        settings={"sync_interval_minutes_idle": "30"},
    )

    assert seconds == 0
    assert state.next_poll_at is None
    # No job should have been added.
    assert callback_calls == []
    scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_resumes_after_clear():
    """After the flag clears, schedule_next arms a real job again."""
    async def callback(_car_id: int) -> None:
        pass

    scheduler = SyncScheduler(
        sync_callback=callback,
        settings_provider=lambda: {"sync_enabled": "true"},
    )
    scheduler.start()

    state = CarSyncState(last_state="IDLE", auth_invalid=True)
    scheduler.schedule_next(42, state, None, {"sync_interval_minutes_idle": "30"})
    assert state.next_poll_at is None

    # Now the user re-saved creds → flag cleared.
    state.auth_invalid = False
    seconds = scheduler.schedule_next(
        42, state, None, {"sync_interval_minutes_idle": "30"},
    )
    assert seconds == 30 * 60
    assert state.next_poll_at is not None
    scheduler.stop()


# ---------------------------------------------------------------------------
# Orchestrator.clear_auth_invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_clear_auth_invalid_resets_state():
    orch = SyncOrchestrator()
    state = orch.ensure_state(7)
    state.auth_invalid = True
    state.consecutive_failures = 4
    state.last_error = "credentials_invalid"

    cleared = orch.clear_auth_invalid([7, 99])  # 99 doesn't exist
    assert cleared == [7]
    assert state.auth_invalid is False
    assert state.consecutive_failures == 0
    assert state.last_error is None


@pytest.mark.asyncio
async def test_orchestrator_clear_auth_invalid_no_op_when_not_set():
    orch = SyncOrchestrator()
    orch.ensure_state(7)  # auth_invalid defaults False
    cleared = orch.clear_auth_invalid([7])
    assert cleared == []


# ---------------------------------------------------------------------------
# PUT /api/settings cupra_* clears the flag and triggers a sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_settings_cupra_clears_auth_invalid_flag(
    authed_client, test_sessionmaker, app
):
    # Insert a car for the bootstrap user.
    from sqlalchemy import select
    async with test_sessionmaker() as s:
        user = (
            await s.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        car = Car(
            user_id=user.id,
            make="Cupra", model="Born", battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
            provider="cupra_connect", provider_vehicle_id="VIN-Y",
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        car_id = car.id

    # Inject an orchestrator with the car's state in auth_invalid mode.
    orch = SyncOrchestrator()
    state = orch.ensure_state(car_id)
    state.auth_invalid = True
    state.last_error = "credentials_invalid"
    state.consecutive_failures = 5

    # Stub poll_worker so the triggered sync doesn't try real auth.
    sync_calls: list[int] = []

    async def stub_worker(job: SyncJob, st: CarSyncState):
        sync_calls.append(job.car_id)
        return st

    orch.set_poll_worker(stub_worker)
    app.state.sync_orchestrator = orch

    # Save a cupra password — flag should clear, sync_car kicked off.
    r = await authed_client.put(
        "/api/settings",
        json={"key": "cupra_password", "value": "new-secret"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text

    # Give the fire-and-forget sync_car task a chance to land.
    for _ in range(10):
        await asyncio.sleep(0.01)
        if not state.auth_invalid:
            break

    assert state.auth_invalid is False
    assert state.last_error is None
    assert state.consecutive_failures == 0
    assert car_id in sync_calls


@pytest.mark.asyncio
async def test_put_settings_non_cupra_key_does_not_clear_auth(
    authed_client, app
):
    """Non-cupra setting changes don't touch the auth state — only
    credential resaves should recover the user."""
    orch = SyncOrchestrator()
    state = orch.ensure_state(1)
    state.auth_invalid = True
    state.last_error = "credentials_invalid"

    sync_calls: list[int] = []

    async def stub_worker(job: SyncJob, st: CarSyncState):
        sync_calls.append(job.car_id)
        return st

    orch.set_poll_worker(stub_worker)
    app.state.sync_orchestrator = orch

    r = await authed_client.put(
        "/api/settings",
        json={"key": "default_home_rate_p_per_kwh", "value": "9.0"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200

    await asyncio.sleep(0.05)

    assert state.auth_invalid is True
    assert sync_calls == []
