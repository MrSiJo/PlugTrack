"""Tests for the production poll-worker.

We mock `vehicle_state_fetcher` to script telemetry and assert the
worker writes the right rows + emits the right events. pycupra itself
is NEVER imported — the adapter_provider returns a sentinel object that
the mocked fetcher ignores.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from plugtrack.models import (
    Car,
    ChargingSession,
    Location,
    PlugInRecord,
    Setting,
    SyncRun,
    User,
)
from plugtrack.plugins.pycupra.models import Position, VehicleState
from plugtrack.services.event_bus import EventBus, SyncEvent
from plugtrack.services.sync_orchestrator import CarSyncState, SyncJob
from plugtrack.services.sync_worker import (
    ProductionPollWorker,
    _AuthError,
    clear_cached_connections,
    production_poll_worker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=offset_seconds
    )


def _vehicle(
    *,
    cable: bool,
    charging: bool,
    soc: int,
    raw: str = "",
    power_kw: float | None = None,
    captured_at: datetime | None = None,
    position: Position | None = None,
) -> VehicleState:
    return VehicleState(
        battery_level=soc,
        charging=charging,
        charging_state=charging,
        charging_state_raw=raw,
        charging_power=power_kw,
        charging_time_left=None,
        target_soc=80,
        charging_cable_connected=cable,
        charging_cable_locked=cable,
        external_power=cable,
        energy_flow="charging" if charging else None,
        vehicle_online=True,
        last_connected=captured_at or _ts(),
        distance_km=12345,
        electric_range_km=200,
        position=position,
        car_captured_timestamp=captured_at or _ts(),
    )


class _RecordingBus(EventBus):
    """EventBus subclass that also keeps a flat list of events for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[SyncEvent] = []

    async def publish(self, event: SyncEvent) -> None:
        self.events.append(event)
        await super().publish(event)

    def event_names(self) -> list[str]:
        return [e.event for e in self.events]

    def first(self, name: str) -> SyncEvent:
        for e in self.events:
            if e.event == name:
                return e
        raise AssertionError(f"event {name!r} not emitted; got {self.event_names()}")


@pytest_asyncio.fixture
async def seeded(test_sessionmaker):
    """Insert one user + one car + the home-rate setting."""
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
            provider="cupra_connect",
            provider_vehicle_id="VIN-TEST",
        )
        session.add(car)
        session.add(
            Setting(
                key="default_home_rate_p_per_kwh",
                value="7.5",
                value_type="float",
                group_name="cost",
                label="home rate",
                description=None,
                default_value="7.5",
                is_secret=False,
            )
        )
        await session.commit()
        await session.refresh(car)
    return {"user_id": user.id, "car_id": car.id}


def _make_worker(
    test_sessionmaker,
    bus: _RecordingBus,
    fetcher,
    *,
    adapter=None,
) -> ProductionPollWorker:
    async def _adapter(car: Car) -> Any:
        if adapter is not None:
            return await adapter(car)
        return object()  # opaque sentinel — the mocked fetcher ignores it

    async def _settings(user_id: int) -> dict:
        # Read the setting table directly so the home-rate seeded by
        # the fixture is picked up.
        async with test_sessionmaker() as session:
            from plugtrack.services.sync_worker import get_user_sync_settings
            return await get_user_sync_settings(session, user_id)

    return ProductionPollWorker(
        db_sessionmaker=test_sessionmaker,
        settings_provider=_settings,
        adapter_provider=_adapter,
        bus=bus,
        vehicle_state_fetcher=fetcher,
    )


# ---------------------------------------------------------------------------
# Happy-path: full plug-in → charge → done → unplug cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_to_plugged_in_opens_plug_in_record(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    state = CarSyncState(last_state="IDLE")
    telemetry = _vehicle(cable=True, charging=False, soc=40, captured_at=_ts(60))

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    job = SyncJob(job_id="j1", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)

    assert new_state.last_state == "PLUGGED_IN"
    assert new_state.last_soc == 40
    assert new_state.consecutive_failures == 0

    # Row was written.
    async with test_sessionmaker() as session:
        rows = (await session.execute(select(PlugInRecord))).scalars().all()
        assert len(rows) == 1
        assert rows[0].plug_in_soc == 40
        assert rows[0].plug_out_at is None

    names = bus.event_names()
    assert "sync.started" in names
    assert "sync.poll_completed" in names
    assert "sync.plug_in_opened" in names
    assert "sync.completed" in names


@pytest.mark.asyncio
async def test_plugged_in_to_charging_opens_session(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    # Pre-seed: we're already PLUGGED_IN with an open plug_in_record.
    async with test_sessionmaker() as session:
        pir = PlugInRecord(
            user_id=seeded["user_id"],
            car_id=car_id,
            plug_in_at=_ts(),
            plug_in_soc=40,
        )
        session.add(pir)
        await session.commit()
        await session.refresh(pir)
        plug_in_id = pir.id

    state = CarSyncState(
        last_state="PLUGGED_IN",
        last_soc=40,
        last_car_captured_timestamp=_ts(),
    )
    telemetry = _vehicle(
        cable=True, charging=True, soc=41, raw="charging",
        power_kw=7.0, captured_at=_ts(120),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    # Prime the scratch buffer to point at the existing plug_in_record.
    from plugtrack.services.sync_worker import _PlugInScratch
    worker._scratch[car_id] = _PlugInScratch(plug_in_record_id=plug_in_id)

    job = SyncJob(job_id="j2", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)
    assert new_state.last_state == "CHARGING"

    async with test_sessionmaker() as session:
        sessions = (await session.execute(select(ChargingSession))).scalars().all()
        assert len(sessions) == 1
        assert sessions[0].plug_in_record_id == plug_in_id
        assert sessions[0].start_soc == 41
        assert sessions[0].charging_type == "ac"
        assert sessions[0].charge_end_at is None

    assert "sync.session_opened" in bus.event_names()


@pytest.mark.asyncio
async def test_charging_to_done_closes_session_with_cost(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    async with test_sessionmaker() as session:
        pir = PlugInRecord(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_at=_ts(), plug_in_soc=40,
        )
        session.add(pir)
        await session.commit()
        await session.refresh(pir)

        cs = ChargingSession(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_record_id=pir.id,
            date=_ts().date(),
            charge_start_at=_ts(60),
            start_soc=41, end_soc=41, kwh_added=0.0,
            charging_type="ac", charging_mode="unknown",
            source="synthesis",
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)
        session_id = cs.id

    state = CarSyncState(
        last_state="CHARGING",
        last_soc=41,
        last_car_captured_timestamp=_ts(60),
    )
    telemetry = _vehicle(
        cable=True, charging=False, soc=80, raw="readyForCharging",
        captured_at=_ts(3600),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    from plugtrack.services.sync_worker import _PlugInScratch
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=pir.id,
        open_session_id=session_id,
        session_ids=[session_id],
        session_start_at=_ts(60),
    )

    job = SyncJob(job_id="j3", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)
    assert new_state.last_state == "CHARGING_DONE"

    async with test_sessionmaker() as session:
        cs = await session.get(ChargingSession, session_id)
        assert cs is not None
        assert cs.charge_end_at is not None
        assert cs.end_soc == 80
        # 80-41 = 39 percentage points * 77 kWh / 100 = 30.03 kWh
        assert abs(cs.kwh_added - 30.03) < 0.01
        # 30.03 * 7.5 p = 225.225 → rounded to 225
        assert cs.cost_pence == 225
        assert cs.cost_basis == "home_rate"
        assert cs.tariff_p_per_kwh == 7.5

    assert "sync.session_closed" in bus.event_names()


@pytest.mark.asyncio
async def test_unplug_closes_plug_in_and_attaches_location(
    seeded, test_sessionmaker
):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    async with test_sessionmaker() as session:
        pir = PlugInRecord(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_at=_ts(), plug_in_soc=40,
        )
        session.add(pir)
        await session.commit()
        await session.refresh(pir)
        cs = ChargingSession(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_record_id=pir.id, date=_ts().date(),
            charge_start_at=_ts(60), charge_end_at=_ts(3600),
            start_soc=40, end_soc=80, kwh_added=30.8,
            source="synthesis",
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)
        plug_in_id, session_id = pir.id, cs.id

    state = CarSyncState(
        last_state="CHARGING_DONE", last_soc=80,
        last_car_captured_timestamp=_ts(3600),
    )
    pos = Position(lat=51.5074, lng=-0.1278, captured_at=_ts(7200))
    telemetry = _vehicle(
        cable=False, charging=False, soc=80,
        captured_at=_ts(7200), position=pos,
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    from plugtrack.services.sync_worker import _PlugInScratch
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id,
        session_ids=[session_id],
        positions=[pos],  # already-tracked position from earlier polls
    )

    job = SyncJob(job_id="j4", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)
    assert new_state.last_state == "IDLE"

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        assert pir is not None
        assert pir.plug_out_at is not None
        assert pir.location_id is not None

        loc = await session.get(Location, pir.location_id)
        assert loc is not None
        assert abs(loc.centroid_lat - 51.5074) < 0.001

        cs = await session.get(ChargingSession, session_id)
        assert cs is not None
        assert cs.location_id == pir.location_id

    names = bus.event_names()
    assert "sync.plug_in_closed" in names
    assert "sync.session_updated" in names


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_failure_emits_sync_failed(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    state = CarSyncState(last_state="IDLE")

    async def bad_adapter(car: Car) -> Any:
        raise _AuthError("nope")

    async def fetcher(_conn, _vid):
        raise AssertionError("should not be called when auth fails")

    worker = _make_worker(test_sessionmaker, bus, fetcher, adapter=bad_adapter)
    job = SyncJob(job_id="j-auth", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)

    assert new_state.consecutive_failures == 1
    assert new_state.last_error == "credentials_invalid"

    failed = bus.first("sync.failed")
    assert failed.data["reason"] == "credentials_invalid"

    # SyncRun row should reflect the failure.
    async with test_sessionmaker() as session:
        runs = (await session.execute(select(SyncRun))).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].error_reason == "credentials_invalid"


@pytest.mark.asyncio
async def test_network_failure_during_fetch_emits_sync_failed(
    seeded, test_sessionmaker
):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    state = CarSyncState(last_state="IDLE")

    async def fetcher(_conn, _vid):
        raise RuntimeError("connection reset")

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    job = SyncJob(job_id="j-net", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)

    assert new_state.consecutive_failures == 1
    assert new_state.last_error == "network"
    assert bus.first("sync.failed").data["reason"] == "network"


# ---------------------------------------------------------------------------
# Stale-telemetry no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_telemetry_emits_no_change_and_writes_no_rows(
    seeded, test_sessionmaker
):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    captured = _ts(60)
    state = CarSyncState(
        last_state="PLUGGED_IN",
        last_soc=40,
        last_car_captured_timestamp=captured,
    )
    telemetry = _vehicle(
        cable=True, charging=False, soc=40, captured_at=captured,
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    job = SyncJob(job_id="j-stale", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)
    assert new_state.last_state == "PLUGGED_IN"

    poll_evt = bus.first("sync.poll_completed")
    assert poll_evt.data["no_change"] is True
    completed = bus.first("sync.completed")
    assert completed.data["transitions"] == []

    async with test_sessionmaker() as session:
        assert (await session.execute(select(PlugInRecord))).scalars().all() == []
        assert (await session.execute(select(ChargingSession))).scalars().all() == []


# ---------------------------------------------------------------------------
# Spec-shaped façade still works.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_production_poll_worker_function_facade(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    async def fetcher(_conn, _vid):
        return _vehicle(cable=True, charging=False, soc=42, captured_at=_ts(60))

    async def adapter(_car):
        return object()

    async def settings(user_id: int) -> dict:
        return {"default_home_rate_p_per_kwh": "7.5"}

    state = CarSyncState(last_state="IDLE")
    job = SyncJob(job_id="j-facade", car_id=car_id, kind="force")

    # The function takes `car` for spec compatibility; pass a stub.
    async with test_sessionmaker() as session:
        car = await session.get(Car, car_id)

    new_state = await production_poll_worker(
        job, car, state, bus,
        db_sessionmaker=test_sessionmaker,
        settings_provider=settings,
        adapter_provider=adapter,
        vehicle_state_fetcher=fetcher,
    )
    assert new_state.last_state == "PLUGGED_IN"
    assert "sync.plug_in_opened" in bus.event_names()


# ---------------------------------------------------------------------------
# Phantom-session detection: the worker writes a placeholder row when the
# state machine flags an IDLE→IDLE SoC jump.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phantom_session_writes_placeholder_row(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    # Car came online with a much higher SoC than we'd last seen — the
    # entire charge happened off-poll. State stays IDLE.
    state = CarSyncState(
        last_state="IDLE",
        last_soc=60,
        last_car_captured_timestamp=_ts(),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=86, captured_at=_ts(1800),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    job = SyncJob(job_id="jp", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)

    assert new_state.last_state == "IDLE"
    assert new_state.last_soc == 86

    async with test_sessionmaker() as session:
        rows = (await session.execute(select(ChargingSession))).scalars().all()
        assert len(rows) == 1
        cs = rows[0]
        assert cs.source == "phantom"
        assert cs.start_soc == 60
        assert cs.end_soc == 86
        # 26 pp * 77 kWh / 100 = 20.02 kWh
        assert abs(cs.kwh_added - 20.02) < 0.01
        # SQLite strips tz info on round-trip; compare against the naive form.
        assert cs.charge_start_at.replace(tzinfo=None) == _ts().replace(tzinfo=None)
        assert cs.charge_end_at.replace(tzinfo=None) == _ts(1800).replace(tzinfo=None)
        assert cs.plug_in_record_id is None
        assert cs.location_id is None
        assert cs.cost_pence is None
        assert cs.cost_basis == "unknown"
        assert cs.interrupted is True
        assert cs.charging_type == "unknown"

    assert "sync.phantom_session_created" in bus.event_names()


@pytest.mark.asyncio
async def test_phantom_below_threshold_writes_nothing(seeded, test_sessionmaker):
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    state = CarSyncState(
        last_state="IDLE", last_soc=60, last_car_captured_timestamp=_ts(),
    )
    # 60 → 63 = 3 pp, below the 5 pp threshold.
    telemetry = _vehicle(cable=False, charging=False, soc=63, captured_at=_ts(60))

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    job = SyncJob(job_id="jp2", car_id=car_id, kind="periodic")
    await worker.run(job, state)

    async with test_sessionmaker() as session:
        rows = (await session.execute(select(ChargingSession))).scalars().all()
        assert rows == []

    assert "sync.phantom_session_created" not in bus.event_names()


# ---------------------------------------------------------------------------
# clear_cached_connections is exposed.
# ---------------------------------------------------------------------------


def test_clear_cached_connections_is_idempotent():
    # Should never raise even if cache is already empty.
    clear_cached_connections()
    clear_cached_connections()
