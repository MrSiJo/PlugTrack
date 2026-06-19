from __future__ import annotations

import datetime as dt

import pytest

from plugtrack.models import ChargingSession
from plugtrack.services import insights_stats as ins


async def _mk(sm, *, user_id, car_id, when, kwh, cost_pence, ctype="ac",
              network=None, source="manual", odometer_km=None):
    async with sm() as s:
        s.add(ChargingSession(
            user_id=user_id, car_id=car_id, date=when, start_soc=20, end_soc=80,
            kwh_added=kwh, charging_type=ctype, charging_mode="manual",
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence is not None else "unknown",
            charge_network=network, source=source, odometer_at_session_km=odometer_km,
            charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.timezone.utc),
        ))
        await s.commit()


def test_resolve_granularity():
    base = dt.date(2026, 1, 1)
    assert ins.resolve_granularity(base, base + dt.timedelta(days=10)) == "daily"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=31)) == "daily"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=60)) == "weekly"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=186)) == "weekly"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=200)) == "monthly"


@pytest.mark.asyncio
async def test_over_time_buckets_daily(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 1), kwh=10.0, cost_pence=200)
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 1), kwh=5.0, cost_pence=100)
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 3), kwh=8.0, cost_pence=None)
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=99.0, cost_pence=9999, source="unconfirmed")
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=dt.date(2026, 6, 1), date_to=dt.date(2026, 6, 30), granularity="daily")
    assert out == [
        {"period": "2026-06-01", "spend_pence": 300, "kwh": 15.0, "sessions": 2},
        {"period": "2026-06-03", "spend_pence": 0, "kwh": 8.0, "sessions": 1},
    ]


@pytest.mark.asyncio
async def test_over_time_weekly_uses_monday(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    # 2026-06-03 is a Wednesday; its week-Monday is 2026-06-01.
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 3), kwh=4.0, cost_pence=80)
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=dt.date(2026, 1, 1), date_to=dt.date(2026, 6, 30), granularity="weekly")
    assert out[0]["period"] == "2026-06-01"


@pytest.mark.asyncio
async def test_home_public_split(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 1), kwh=10.0, cost_pence=200, ctype="ac")
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=30.0, cost_pence=1500, ctype="dc", network="Tesla")
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 3), kwh=5.0, cost_pence=None, ctype="dc")
    async with test_sessionmaker() as s:
        split = await ins.home_public_split(s, user_id=uid, date_from=None, date_to=None)
    assert split["home"] == {"spend_pence": 200, "kwh": 10.0, "sessions": 1, "avg_p_per_kwh": 20.0}
    # public: cost only on the costed DC session; avg over costed kWh only (30.0)
    assert split["public"] == {"spend_pence": 1500, "kwh": 35.0, "sessions": 2, "avg_p_per_kwh": 50.0}


@pytest.mark.asyncio
async def test_network_breakdown_ranked_and_unknown(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 1), kwh=30.0, cost_pence=1500, ctype="dc", network="Tesla")
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=10.0, cost_pence=200, ctype="ac", network=None)
    async with test_sessionmaker() as s:
        rows = await ins.network_breakdown(s, user_id=uid, date_from=None, date_to=None)
    assert [r["network"] for r in rows] == ["Tesla", "Unknown"]
    assert rows[0]["spend_pence"] == 1500
    assert rows[1]["network"] == "Unknown" and rows[1]["spend_pence"] == 200


@pytest.mark.asyncio
async def test_efficiency_null_without_odometer(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=10.0, cost_pence=200)
    async with test_sessionmaker() as s:
        out = await ins.efficiency_over_time(
            s, user_id=uid, date_from=dt.date(2026, 6, 1), date_to=dt.date(2026, 6, 30), granularity="daily")
    assert out == [{"period": "2026-06-02", "observed_mi_per_kwh": None, "cost_per_mile_p": None}]


@pytest.mark.asyncio
async def test_efficiency_with_odometer_span(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    # Reference reading before the window, then a reading inside it: 160.9344 km = 100 mi driven.
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 5, 30), kwh=1.0, cost_pence=10, odometer_km=1000.0)
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=25.0, cost_pence=500, odometer_km=1000.0 + 100 * 1.609344)
    async with test_sessionmaker() as s:
        out = await ins.efficiency_over_time(
            s, user_id=uid, date_from=dt.date(2026, 6, 1), date_to=dt.date(2026, 6, 30), granularity="daily")
    pt = next(p for p in out if p["period"] == "2026-06-02")
    assert pt["observed_mi_per_kwh"] == pytest.approx(4.0, abs=0.01)   # 100 mi / 25 kWh
    assert pt["cost_per_mile_p"] == pytest.approx(5.0, abs=0.01)        # 500 p / 100 mi


@pytest.mark.asyncio
async def test_aggregators_user_isolation(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    from plugtrack.models import User
    async with test_sessionmaker() as s:
        other = User(username="bob", password_hash="x")
        s.add(other)
        await s.commit()
        await s.refresh(other)
        other_id = other.id
    await _mk(test_sessionmaker, user_id=other_id, car_id=car, when=dt.date(2026, 6, 1), kwh=10.0, cost_pence=200)
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=None, date_to=None, granularity="daily")
    assert out == []
