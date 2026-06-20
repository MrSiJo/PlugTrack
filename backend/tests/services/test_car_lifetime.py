"""Tests for services.car_lifetime.compute_car_lifetime."""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pytest

from plugtrack.models import Car, ChargingSession, User
from plugtrack.services.car_lifetime import compute_car_lifetime


async def _make_user(sm, username="alice") -> int:
    async with sm() as s:
        u = User(username=username, password_hash="x")
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def _make_car(sm, user_id: int, *, active=True) -> int:
    async with sm() as s:
        car = Car(
            user_id=user_id, make="Cupra", model="Born",
            battery_kwh=58.0, nominal_efficiency_mi_per_kwh=4.0,
            provider="manual", active=active,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


async def _add_session(
    sm, *, user_id, car_id, when, kwh, cost_pence=None,
    ctype="ac", odometer_km=None
) -> None:
    async with sm() as s:
        s.add(ChargingSession(
            user_id=user_id, car_id=car_id,
            date=when, start_soc=20, end_soc=80,
            kwh_added=kwh, charging_type=ctype, charging_mode="manual",
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence is not None else "unknown",
            source="manual",
            odometer_at_session_km=odometer_km,
            charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.timezone.utc),
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_lifetime_basic_aggregates(test_sessionmaker):
    """compute_car_lifetime returns correct span, totals, avg p/kWh."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid)

    # 3 home sessions (AC), 2 costed
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 1, 10), kwh=10.0, cost_pence=200, ctype="ac")
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 3, 20), kwh=20.0, cost_pence=400, ctype="ac")
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 6, 15), kwh=15.0, cost_pence=None, ctype="dc")

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    assert result["ownership_span"]["first"] == "2026-01-10"
    assert result["ownership_span"]["last"] == "2026-06-15"
    assert result["total_sessions"] == 3
    assert result["total_kwh"] == pytest.approx(45.0)
    assert result["total_cost_pence"] == 600
    # avg p/kWh: 600 pence / 30 costed kWh = 20.0
    assert result["lifetime_avg_p_per_kwh"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_lifetime_mi_per_kwh(test_sessionmaker):
    """lifetime_mi_per_kwh is computed from odometer deltas / total kwh."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid)

    KM_PER_MILE = 1.609344
    # Two sessions: odo goes 1000 → 1000 + 100*KPM km (100 miles driven), 25 kWh
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 1, 1), kwh=1.0, cost_pence=10,
                       ctype="ac", odometer_km=1000.0)
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 3, 1), kwh=25.0, cost_pence=500,
                       ctype="ac", odometer_km=1000.0 + 100 * KM_PER_MILE)

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    # 100 miles / (1 + 25) kWh = 100/26 ≈ 3.846 mi/kWh
    expected = round(100.0 / 26.0, 3)
    assert result["lifetime_mi_per_kwh"] == pytest.approx(expected, abs=0.01)


@pytest.mark.asyncio
async def test_lifetime_home_public_split(test_sessionmaker):
    """home_public reflects AC vs DC split for the car."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid)

    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 1, 1), kwh=10.0, cost_pence=200, ctype="ac")
    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2026, 2, 1), kwh=30.0, cost_pence=900, ctype="dc")

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    assert result["home_public"]["home"]["sessions"] == 1
    assert result["home_public"]["home"]["kwh"] == pytest.approx(10.0)
    assert result["home_public"]["public"]["sessions"] == 1
    assert result["home_public"]["public"]["kwh"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_lifetime_no_sessions(test_sessionmaker):
    """A car with no sessions returns zeros and null span/avg/efficiency."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid)

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    assert result["ownership_span"] == {"first": None, "last": None}
    assert result["total_sessions"] == 0
    assert result["total_kwh"] == pytest.approx(0.0)
    assert result["total_cost_pence"] == 0
    assert result["lifetime_avg_p_per_kwh"] is None
    assert result["lifetime_mi_per_kwh"] is None


@pytest.mark.asyncio
async def test_lifetime_archived_car(test_sessionmaker):
    """compute_car_lifetime works for archived (active=False) cars."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid, active=False)

    await _add_session(test_sessionmaker, user_id=uid, car_id=car_id,
                       when=dt.date(2025, 6, 1), kwh=50.0, cost_pence=1000, ctype="ac")

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    assert result["total_sessions"] == 1
    assert result["total_kwh"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_lifetime_user_isolation(test_sessionmaker):
    """compute_car_lifetime only returns data belonging to the given user_id."""
    uid_a = await _make_user(test_sessionmaker, "alice")
    uid_b = await _make_user(test_sessionmaker, "bob")
    car_a = await _make_car(test_sessionmaker, uid_a)
    car_b = await _make_car(test_sessionmaker, uid_b)

    await _add_session(test_sessionmaker, user_id=uid_a, car_id=car_a,
                       when=dt.date(2026, 1, 1), kwh=10.0, cost_pence=200)
    await _add_session(test_sessionmaker, user_id=uid_b, car_id=car_b,
                       when=dt.date(2026, 1, 2), kwh=50.0, cost_pence=1000)

    async with test_sessionmaker() as s:
        result_a = await compute_car_lifetime(s, user_id=uid_a, car_id=car_a)
        result_b = await compute_car_lifetime(s, user_id=uid_b, car_id=car_b)

    assert result_a["total_sessions"] == 1
    assert result_a["total_kwh"] == pytest.approx(10.0)
    assert result_b["total_sessions"] == 1
    assert result_b["total_kwh"] == pytest.approx(50.0)
