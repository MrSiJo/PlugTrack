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
