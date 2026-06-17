import datetime as dt
import pytest

from plugtrack.models import ChargingSession
from plugtrack.services.usage_stats import build_usage_snapshot


async def _mk(sm, *, user_id, car_id, when, kwh, cost_pence, ctype="ac",
              network=None, source="manual"):
    async with sm() as s:
        s.add(ChargingSession(
            user_id=user_id, car_id=car_id, date=when, start_soc=20, end_soc=80,
            kwh_added=kwh, charging_type=ctype, charging_mode="manual",
            cost_pence=cost_pence, cost_basis="home_rate" if cost_pence else "unknown",
            charge_network=network, source=source,
            charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.timezone.utc),
        ))
        await s.commit()


def _w(snap, label):
    return next(w for w in snap.windows if w.label == label)


@pytest.mark.asyncio
async def test_window_totals_and_avg(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    today = dt.date(2026, 6, 17)
    # two this-month charges: one costed, one not
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 2), kwh=10.0, cost_pence=200)
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 10), kwh=5.0, cost_pence=None)
    # a last-month charge (excluded from "this month")
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 5, 20), kwh=8.0, cost_pence=160)
    # an unconfirmed row (excluded everywhere)
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 5), kwh=99.0, cost_pence=9999, source="unconfirmed")

    async with test_sessionmaker() as s:
        snap = await build_usage_snapshot(s, user_id=user_id, today=today, distance_unit="mi")

    tm = _w(snap, "this month")
    assert tm.sessions == 2
    assert tm.spend == "£2.00"
    assert tm.energy == "15.0 kWh"
    assert tm.avg_p_per_kwh == "20.0 p/kWh"   # 200p / 10kWh costed (the uncosted 5kWh excluded from avg)

    lm = _w(snap, "last month")
    assert lm.sessions == 1 and lm.spend == "£1.60"

    life = _w(snap, "lifetime")
    assert life.sessions == 3            # unconfirmed excluded
    assert life.spend == "£3.60"

    assert snap.today == "2026-06-17"
    assert snap.distance_unit == "mi"


@pytest.mark.asyncio
async def test_empty_user_zeroed(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        snap = await build_usage_snapshot(s, user_id=user_id, today=dt.date(2026, 6, 17), distance_unit="mi")
    tm = _w(snap, "this month")
    assert tm.sessions == 0 and tm.spend == "£0.00" and tm.energy == "0.0 kWh"
    assert tm.avg_p_per_kwh is None


def _split(snap, label):
    return next(sp for sp in snap.splits if sp.label == label)


@pytest.mark.asyncio
async def test_home_public_and_network_split(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    today = dt.date(2026, 6, 17)
    # home (ac) this month
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 3), kwh=10.0, cost_pence=200, ctype="ac")
    # public (dc) this month, two networks
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 4), kwh=30.0, cost_pence=1500, ctype="dc", network="Tesla")
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 5), kwh=20.0, cost_pence=1000, ctype="dc", network="Osprey")

    async with test_sessionmaker() as s:
        snap = await build_usage_snapshot(s, user_id=user_id, today=today, distance_unit="mi")

    tm = _split(snap, "this month")
    assert "£2.00" in tm.home and "10.0 kWh" in tm.home
    assert "£25.00" in tm.public and "50.0 kWh" in tm.public
    assert "Tesla" in tm.by_network and "£15.00" in tm.by_network["Tesla"]
    assert "Osprey" in tm.by_network and "£10.00" in tm.by_network["Osprey"]
    # lifetime split also present
    assert any(sp.label == "lifetime" for sp in snap.splits)


@pytest.mark.asyncio
async def test_mileage_pace(test_sessionmaker, seeded_user_car):
    from plugtrack.services import mileage_tracking as mt
    user_id, car_id = seeded_user_car
    today = dt.date(2026, 6, 17)
    start = dt.date(2026, 1, 1)   # ~167 days elapsed
    async with test_sessionmaker() as s:
        await mt.set_tracking(s, user_id=user_id, car_id=car_id, start_date=start,
                              opening_miles=10000, annual_mileage_target_miles=10000, today=today)
        await s.commit()
    # a charge carrying an odometer reading 12,000 mi -> 2,000 mi this year
    await _mk(test_sessionmaker, user_id=user_id, car_id=car_id, when=dt.date(2026, 6, 1), kwh=10.0, cost_pence=200)
    async with test_sessionmaker() as s:
        from plugtrack.models import ChargingSession as CS
        from sqlalchemy import select as _sel
        row = (await s.execute(_sel(CS).where(CS.user_id == user_id))).scalars().first()
        row.odometer_at_session_km = 12000 * 1.609344
        await s.commit()

    async with test_sessionmaker() as s:
        snap = await build_usage_snapshot(s, user_id=user_id, today=today, distance_unit="mi")

    assert len(snap.mileage) == 1
    m = snap.mileage[0]
    assert m.current == "12,000 mi"
    assert "2,000 mi" in m.this_year
    assert m.target == "10,000 mi/yr target"
    assert m.pace is not None and "mi" in m.pace   # linear extrapolation rendered
