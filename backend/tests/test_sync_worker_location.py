"""Phase 5.2 tests — location clustering wired into the production worker.

Covers the close-plug-in branch where the worker:

1. Computes the centroid (mean lat/lng) of the in-window position buffer.
2. Runs `find_or_create_location` against the user.
3. Patches `location_id` onto the plug_in_record + every contained session.
4. If a NEW location was created, schedules a fire-and-forget
   `_geocode_async` task that writes `address` / `address_provider` /
   `address_fetched_at` back to the row.

We mock the geocoding provider via monkeypatching `get_provider` in the
service module so no HTTP calls are made.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy import select

from plugtrack.models import (
    Car,
    ChargingSession,
    Location,
    PlugInRecord,
    Setting,
    User,
)
from plugtrack.plugins.pycupra.models import Position, VehicleState
from plugtrack.services import sync_worker as sw
from plugtrack.services.event_bus import EventBus, SyncEvent
from plugtrack.services.geocoding import GeocodeResult, NoOpProvider
from plugtrack.services.sync_orchestrator import CarSyncState, SyncJob
from plugtrack.services.sync_worker import ProductionPollWorker, _PlugInScratch


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
    captured_at: Optional[datetime] = None,
    position: Optional[Position] = None,
) -> VehicleState:
    return VehicleState(
        battery_level=soc,
        charging=charging,
        charging_state=charging,
        charging_state_raw=raw,
        charging_power=None,
        charging_time_left=None,
        target_soc=80,
        charging_cable_connected=cable,
        charging_cable_locked=cable,
        external_power=cable,
        energy_flow=None,
        vehicle_online=True,
        last_connected=captured_at or _ts(),
        distance_km=12345,
        electric_range_km=200,
        position=position,
        car_captured_timestamp=captured_at or _ts(),
    )


class _RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[SyncEvent] = []

    async def publish(self, event: SyncEvent) -> None:
        self.events.append(event)
        await super().publish(event)


@pytest_asyncio.fixture
async def seeded(test_sessionmaker):
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


def _make_worker(test_sessionmaker, bus, fetcher) -> ProductionPollWorker:
    async def _adapter(car: Car) -> Any:
        return object()

    async def _settings(user_id: int) -> dict:
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
# Centroid clustering: 3 position samples → averaged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_centroid_of_three_samples(seeded, test_sessionmaker, monkeypatch):
    """Three GPS samples during the plug-in window → centroid attached to
    plug_in_record AND the contained ChargingSession."""
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    # Insert an open plug-in + an associated session (mimicking what
    # earlier polls in this window would have written).
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

    p1 = Position(lat=51.500, lng=-0.100, captured_at=_ts(60))
    p2 = Position(lat=51.501, lng=-0.101, captured_at=_ts(120))
    p3 = Position(lat=51.502, lng=-0.102, captured_at=_ts(180))

    # On the closing poll the cable is removed.
    state = CarSyncState(
        last_state="CHARGING_DONE", last_soc=80,
        last_car_captured_timestamp=_ts(3600),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=80, captured_at=_ts(7200), position=None,
    )

    async def fetcher(_conn, _vid):
        return telemetry

    # Disable geocoding for this test — only the clustering branch is
    # under test.
    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _settings: NoOpProvider())

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id,
        session_ids=[session_id],
        positions=[p1, p2, p3],
    )

    job = SyncJob(job_id="j-centroid", car_id=car_id, kind="periodic")
    new_state = await worker.run(job, state)
    assert new_state.last_state == "IDLE"

    expected_lat = (p1.lat + p2.lat + p3.lat) / 3
    expected_lng = (p1.lng + p2.lng + p3.lng) / 3

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        assert pir is not None
        assert pir.location_id is not None
        cs = await session.get(ChargingSession, session_id)
        assert cs is not None
        assert cs.location_id == pir.location_id

        loc = await session.get(Location, pir.location_id)
        assert loc is not None
        assert loc.centroid_lat == pytest.approx(expected_lat, abs=1e-6)
        assert loc.centroid_lng == pytest.approx(expected_lng, abs=1e-6)


# ---------------------------------------------------------------------------
# New location → geocoder is called and result persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_location_triggers_geocoding(
    seeded, test_sessionmaker, monkeypatch
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
        plug_in_id = pir.id

    pos = Position(lat=51.5074, lng=-0.1278, captured_at=_ts(60))
    state = CarSyncState(
        last_state="PLUGGED_IN", last_soc=40,
        last_car_captured_timestamp=_ts(60),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=40, captured_at=_ts(7200),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    call_log: list[tuple[float, float]] = []

    class _StubProvider:
        name = "test"

        async def reverse(self, lat: float, lng: float):
            call_log.append((lat, lng))
            return GeocodeResult(
                address="10 Downing St, London",
                provider="test",
                lat=lat,
                lng=lng,
            )

    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _s: _StubProvider())

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id, positions=[pos],
    )

    job = SyncJob(job_id="j-geocode", car_id=car_id, kind="periodic")
    await worker.run(job, state)

    # Wait for the fire-and-forget geocode task to finish. Yield the
    # event loop a few times then poll for the row update.
    for _ in range(20):
        await asyncio.sleep(0.01)
        async with test_sessionmaker() as session:
            pir = await session.get(PlugInRecord, plug_in_id)
            if pir is not None and pir.location_id is not None:
                loc = await session.get(Location, pir.location_id)
                if loc is not None and loc.address is not None:
                    break

    assert len(call_log) == 1
    assert call_log[0][0] == pytest.approx(pos.lat, abs=1e-6)
    assert call_log[0][1] == pytest.approx(pos.lng, abs=1e-6)

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        loc = await session.get(Location, pir.location_id)
        assert loc.address == "10 Downing St, London"
        assert loc.address_provider == "test"
        assert loc.address_fetched_at is not None


# ---------------------------------------------------------------------------
# Existing location matched → geocoder NOT called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_location_skips_geocoding(
    seeded, test_sessionmaker, monkeypatch
):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    async with test_sessionmaker() as session:
        # Pre-existing labelled location at the exact coords we'll cluster on.
        existing = Location(
            user_id=seeded["user_id"],
            name="Home",
            centroid_lat=51.5074, centroid_lng=-0.1278,
            radius_m=100,
        )
        session.add(existing)
        pir = PlugInRecord(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_at=_ts(), plug_in_soc=40,
        )
        session.add(pir)
        await session.commit()
        await session.refresh(existing)
        await session.refresh(pir)
        plug_in_id = pir.id
        existing_id = existing.id

    pos = Position(lat=51.5074, lng=-0.1278, captured_at=_ts(60))
    state = CarSyncState(
        last_state="PLUGGED_IN", last_soc=40,
        last_car_captured_timestamp=_ts(60),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=40, captured_at=_ts(7200),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    call_log: list[tuple[float, float]] = []

    class _StubProvider:
        async def reverse(self, lat: float, lng: float):
            call_log.append((lat, lng))
            return GeocodeResult(
                address="should-not-be-called", provider="x", lat=lat, lng=lng
            )

    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _s: _StubProvider())

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id, positions=[pos],
    )

    job = SyncJob(job_id="j-existing", car_id=car_id, kind="periodic")
    await worker.run(job, state)

    # Give any wrongly-spawned task a chance to run.
    for _ in range(5):
        await asyncio.sleep(0.01)

    assert call_log == []

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        assert pir.location_id == existing_id


# ---------------------------------------------------------------------------
# Geocoder failure → location row's address stays NULL but other fields persist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geocoder_failure_leaves_address_null(
    seeded, test_sessionmaker, monkeypatch
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
        plug_in_id = pir.id

    pos = Position(lat=42.0, lng=2.0, captured_at=_ts(60))
    state = CarSyncState(
        last_state="PLUGGED_IN", last_soc=40,
        last_car_captured_timestamp=_ts(60),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=40, captured_at=_ts(7200),
    )

    async def fetcher(_conn, _vid):
        return telemetry

    class _FailingProvider:
        async def reverse(self, lat: float, lng: float):
            return None  # network failure / no match

    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _s: _FailingProvider())

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id, positions=[pos],
    )

    job = SyncJob(job_id="j-geofail", car_id=car_id, kind="periodic")
    await worker.run(job, state)

    # Allow background task to run.
    for _ in range(10):
        await asyncio.sleep(0.01)

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        assert pir.location_id is not None
        loc = await session.get(Location, pir.location_id)
        assert loc is not None
        # Clustering still happened.
        assert loc.centroid_lat == pytest.approx(42.0, abs=1e-6)
        assert loc.centroid_lng == pytest.approx(2.0, abs=1e-6)
        # But the geocode failed silently.
        assert loc.address is None
        assert loc.address_provider is None
        assert loc.address_fetched_at is None


# ---------------------------------------------------------------------------
# Visit tracking: close_plug_in increments Location.visit_count and stamps
# Location.last_visited_at on the resolved cluster.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_plug_in_increments_visit_count(
    seeded, test_sessionmaker, monkeypatch,
):
    bus = _RecordingBus()
    car_id = seeded["car_id"]

    # Seed an open plug-in + session for this window.
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

    pos = Position(lat=51.500, lng=-0.100, captured_at=_ts(60))
    state = CarSyncState(
        last_state="CHARGING_DONE", last_soc=80,
        last_car_captured_timestamp=_ts(3600),
    )
    telemetry = _vehicle(
        cable=False, charging=False, soc=80, captured_at=_ts(7200), position=None,
    )

    async def fetcher(_conn, _vid):
        return telemetry

    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _s: NoOpProvider())

    worker = _make_worker(test_sessionmaker, bus, fetcher)
    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=plug_in_id,
        session_ids=[session_id],
        positions=[pos],
    )

    job = SyncJob(job_id="j-visit", car_id=car_id, kind="periodic")
    await worker.run(job, state)

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, plug_in_id)
        loc = await session.get(Location, pir.location_id)
        assert loc.visit_count == 1
        assert loc.last_visited_at is not None
        # last_visited_at tracks the plug_out_at timestamp.
        assert loc.last_visited_at.replace(tzinfo=None) == _ts(7200).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_repeat_visits_increment_visit_count(
    seeded, test_sessionmaker, monkeypatch,
):
    """Two plug-in cycles at the same location -> visit_count = 2."""
    bus = _RecordingBus()
    car_id = seeded["car_id"]
    monkeypatch.setattr(sw, "get_geocoding_provider", lambda _s: NoOpProvider())

    pos = Position(lat=51.500, lng=-0.100, captured_at=_ts(60))
    telemetry = _vehicle(
        cable=False, charging=False, soc=80, captured_at=_ts(7200), position=None,
    )

    async def fetcher(_conn, _vid):
        return telemetry

    worker = _make_worker(test_sessionmaker, bus, fetcher)

    # ---- First visit ----
    async with test_sessionmaker() as session:
        pir1 = PlugInRecord(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_at=_ts(), plug_in_soc=40,
        )
        session.add(pir1)
        await session.commit()
        await session.refresh(pir1)
        pir1_id = pir1.id

    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=pir1_id, session_ids=[], positions=[pos],
    )
    state = CarSyncState(
        last_state="PLUGGED_IN", last_soc=80,
        last_car_captured_timestamp=_ts(3600),
    )
    await worker.run(SyncJob(job_id="j-v1", car_id=car_id, kind="periodic"), state)

    # ---- Second visit, same lat/lng -> same cluster ----
    async with test_sessionmaker() as session:
        pir2 = PlugInRecord(
            user_id=seeded["user_id"], car_id=car_id,
            plug_in_at=_ts(10_000), plug_in_soc=40,
        )
        session.add(pir2)
        await session.commit()
        await session.refresh(pir2)
        pir2_id = pir2.id

    worker._scratch[car_id] = _PlugInScratch(
        plug_in_record_id=pir2_id, session_ids=[], positions=[pos],
    )
    state2 = CarSyncState(
        last_state="PLUGGED_IN", last_soc=80,
        last_car_captured_timestamp=_ts(11_000),
    )
    await worker.run(SyncJob(job_id="j-v2", car_id=car_id, kind="periodic"), state2)

    async with test_sessionmaker() as session:
        pir = await session.get(PlugInRecord, pir2_id)
        loc = await session.get(Location, pir.location_id)
        assert loc.visit_count == 2
