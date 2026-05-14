"""Tests for the FastAPI app factory + lifespan."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from plugtrack.models import (
    Car,
    CarStateSnapshot,
    PlugInRecord,
    Setting,
    User,
)
from plugtrack.settings.catalogue import CATALOGUE


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "commit" in body


@pytest.mark.asyncio
async def test_lifespan_seeds_catalogue(app, test_sessionmaker):
    # ASGITransport does not drive lifespan events automatically; invoke
    # the FastAPI lifespan context directly to exercise the seeder.
    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            result = await session.execute(select(func.count()).select_from(Setting))
            count = result.scalar_one()
    assert count == len(CATALOGUE)


def test_multi_worker_tripwire_raises(monkeypatch):
    from plugtrack.main import _assert_single_worker

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError, match="WEB_CONCURRENCY=1"):
        _assert_single_worker()


def test_single_worker_allowed(monkeypatch):
    from plugtrack.main import _assert_single_worker

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    _assert_single_worker()  # no raise

    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    _assert_single_worker()  # no raise


@pytest.mark.asyncio
async def test_app_includes_health_route(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/health" in paths
    # Sanity: WEB_CONCURRENCY is not poisoned by another test.
    assert os.getenv("WEB_CONCURRENCY") in (None, "1")


# ---------------------------------------------------------------------------
# Startup watchdog: orphaned plug-in records (plug_out_at IS NULL) are
# closed conservatively when the rehydrated state for the car has since
# reset to IDLE. Without this, an unplug missed across a container
# restart leaves the row hanging forever.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_closes_orphaned_plug_in_when_state_idle(
    app, test_sessionmaker,
):
    snapshot_ts = datetime(2026, 5, 10, 7, 30, tzinfo=timezone.utc)
    plug_in_ts = datetime(2026, 5, 4, 20, 34, tzinfo=timezone.utc)

    async with test_sessionmaker() as s:
        user = User(username="alice", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car = Car(
            user_id=user.id, make="Cupra", model="Born",
            battery_kwh=77.0, nominal_efficiency_mi_per_kwh=3.6,
            provider="cupra_connect", provider_vehicle_id="VIN-T",
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        s.add(CarStateSnapshot(
            car_id=car.id,
            last_state="IDLE",
            last_soc=72,
            last_car_captured_timestamp=snapshot_ts,
        ))
        # An orphaned open plug-in pre-dating the snapshot.
        s.add(PlugInRecord(
            user_id=user.id, car_id=car.id,
            plug_in_at=plug_in_ts, plug_in_soc=69,
        ))
        await s.commit()
        car_id = car.id

    async with app.router.lifespan_context(app):
        pass

    async with test_sessionmaker() as s:
        rows = (await s.execute(
            select(PlugInRecord).where(PlugInRecord.car_id == car_id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].plug_out_at is not None
        # Conservatively closed at the snapshot's captured timestamp + SoC.
        assert rows[0].plug_out_at.replace(tzinfo=None) == snapshot_ts.replace(tzinfo=None)
        assert rows[0].plug_out_soc == 72


@pytest.mark.asyncio
async def test_startup_does_not_touch_open_plug_in_when_still_plugged_in(
    app, test_sessionmaker,
):
    """If the snapshot says PLUGGED_IN/CHARGING, the open row is legitimate."""
    async with test_sessionmaker() as s:
        user = User(username="bob", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car = Car(
            user_id=user.id, make="Cupra", model="Born",
            battery_kwh=77.0, nominal_efficiency_mi_per_kwh=3.6,
            provider="cupra_connect", provider_vehicle_id="VIN-T",
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        s.add(CarStateSnapshot(
            car_id=car.id, last_state="PLUGGED_IN", last_soc=50,
            last_car_captured_timestamp=datetime(2026, 5, 10, tzinfo=timezone.utc),
        ))
        s.add(PlugInRecord(
            user_id=user.id, car_id=car.id,
            plug_in_at=datetime(2026, 5, 10, 7, tzinfo=timezone.utc),
            plug_in_soc=50,
        ))
        await s.commit()
        car_id = car.id

    async with app.router.lifespan_context(app):
        pass

    async with test_sessionmaker() as s:
        rows = (await s.execute(
            select(PlugInRecord).where(PlugInRecord.car_id == car_id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].plug_out_at is None  # left alone
