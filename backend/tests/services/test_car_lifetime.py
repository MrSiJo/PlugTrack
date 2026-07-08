"""Tests for services.car_lifetime.compute_car_lifetime."""

from __future__ import annotations

import datetime as dt

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
            user_id=user_id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=active,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


async def _add_session(
    sm, *, user_id, car_id, when, kwh, cost_pence=None, ctype="ac", odometer_km=None
) -> None:
    async with sm() as s:
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=when,
                start_soc=20,
                end_soc=80,
                kwh_added=kwh,
                charging_type=ctype,
                charging_mode="manual",
                cost_pence=cost_pence,
                cost_basis="home_rate" if cost_pence is not None else "unknown",
                source="manual",
                odometer_at_session_km=odometer_km,
                charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_lifetime_basic_aggregates(test_sessionmaker):
    """compute_car_lifetime returns correct span, totals, avg p/kWh."""
    uid = await _make_user(test_sessionmaker)
    car_id = await _make_car(test_sessionmaker, uid)

    # 3 home sessions (AC), 2 costed
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 1, 10),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 3, 20),
        kwh=20.0,
        cost_pence=400,
        ctype="ac",
    )
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 6, 15),
        kwh=15.0,
        cost_pence=None,
        ctype="dc",
    )

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
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 1, 1),
        kwh=1.0,
        cost_pence=10,
        ctype="ac",
        odometer_km=1000.0,
    )
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 3, 1),
        kwh=25.0,
        cost_pence=500,
        ctype="ac",
        odometer_km=1000.0 + 100 * KM_PER_MILE,
    )

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

    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 1, 1),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2026, 2, 1),
        kwh=30.0,
        cost_pence=900,
        ctype="dc",
    )

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

    await _add_session(
        test_sessionmaker,
        user_id=uid,
        car_id=car_id,
        when=dt.date(2025, 6, 1),
        kwh=50.0,
        cost_pence=1000,
        ctype="ac",
    )

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

    await _add_session(
        test_sessionmaker,
        user_id=uid_a,
        car_id=car_a,
        when=dt.date(2026, 1, 1),
        kwh=10.0,
        cost_pence=200,
    )
    await _add_session(
        test_sessionmaker,
        user_id=uid_b,
        car_id=car_b,
        when=dt.date(2026, 1, 2),
        kwh=50.0,
        cost_pence=1000,
    )

    async with test_sessionmaker() as s:
        result_a = await compute_car_lifetime(s, user_id=uid_a, car_id=car_a)
        result_b = await compute_car_lifetime(s, user_id=uid_b, car_id=car_b)

    assert result_a["total_sessions"] == 1
    assert result_a["total_kwh"] == pytest.approx(10.0)
    assert result_b["total_sessions"] == 1
    assert result_b["total_kwh"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Task 2: estimated_usable_kwh + seasonal_range_span in compute_car_lifetime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifetime_includes_estimated_usable_kwh_and_seasonal_range_span(test_sessionmaker):
    """compute_car_lifetime includes estimated_usable_kwh + seasonal_range_span."""
    uid = await _make_user(test_sessionmaker, "carol")
    # battery_kwh=58.0 (set in _make_car)
    car_id = await _make_car(test_sessionmaker, uid)

    # Three DC sessions across different months, each with ≥40pp SoC delta
    # so they qualify for capacity inference and monthly efficiency
    # Also include odometer data so derived_range_km is computable
    for when, odo in [
        (dt.date(2026, 1, 10), 1000.0),
        (dt.date(2026, 3, 15), 1200.0),
        (dt.date(2026, 5, 20), 1500.0),
    ]:
        async with test_sessionmaker() as s:
            s.add(
                ChargingSession(
                    user_id=uid,
                    car_id=car_id,
                    date=when,
                    start_soc=10,
                    end_soc=80,
                    kwh_added=20.0,
                    charging_type="dc",
                    charging_mode="manual",
                    cost_pence=400,
                    cost_basis="home_rate",
                    source="manual",
                    odometer_at_session_km=odo,
                    charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC),
                )
            )
            await s.commit()

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    # New keys must be present
    assert "estimated_usable_kwh" in result
    assert "seasonal_range_span" in result

    # estimated_usable_kwh: 3 DC qualifying sessions → non-None float
    assert result["estimated_usable_kwh"] is not None
    assert isinstance(result["estimated_usable_kwh"], float)
    # usable_kwh per charge = 20 / (70/100) ≈ 28.57; median of 3 identical = 28.57
    assert result["estimated_usable_kwh"] == pytest.approx(20.0 / 0.70, abs=0.1)

    # seasonal_range_span: 3 months with odometer data → non-None dict with min/max/avg
    span = result["seasonal_range_span"]
    assert span is not None
    assert "min_km" in span
    assert "max_km" in span
    assert "avg_km" in span
    assert span["min_km"] <= span["max_km"]


@pytest.mark.asyncio
async def test_lifetime_estimated_usable_kwh_none_when_no_qualifying(test_sessionmaker):
    """estimated_usable_kwh is None when no sessions qualify for capacity inference."""
    uid = await _make_user(test_sessionmaker, "dave")
    car_id = await _make_car(test_sessionmaker, uid)

    # Session with small SoC delta (< 40pp) — does NOT qualify for capacity inference
    async with test_sessionmaker() as s:
        s.add(
            ChargingSession(
                user_id=uid,
                car_id=car_id,
                date=dt.date(2026, 1, 1),
                start_soc=50,
                end_soc=80,  # 30pp delta < 40pp threshold → doesn't qualify
                kwh_added=5.0,
                charging_type="dc",
                charging_mode="manual",
                cost_pence=100,
                cost_basis="home_rate",
                source="manual",
                charge_end_at=dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC),
            )
        )
        await s.commit()

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    assert result["estimated_usable_kwh"] is None
    assert result["seasonal_range_span"] is None


@pytest.mark.asyncio
async def test_lifetime_archived_car_includes_new_fields(test_sessionmaker):
    """estimated_usable_kwh + seasonal_range_span work for archived cars."""
    uid = await _make_user(test_sessionmaker, "eve")
    car_id = await _make_car(test_sessionmaker, uid, active=False)

    # One qualifying DC session
    async with test_sessionmaker() as s:
        s.add(
            ChargingSession(
                user_id=uid,
                car_id=car_id,
                date=dt.date(2025, 6, 1),
                start_soc=10,
                end_soc=90,
                kwh_added=30.0,
                charging_type="dc",
                charging_mode="manual",
                cost_pence=600,
                cost_basis="home_rate",
                source="manual",
                odometer_at_session_km=2000.0,
                charge_end_at=dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.UTC),
            )
        )
        await s.commit()

    async with test_sessionmaker() as s:
        result = await compute_car_lifetime(s, user_id=uid, car_id=car_id)

    # New keys present for archived car
    assert "estimated_usable_kwh" in result
    assert "seasonal_range_span" in result
    # One qualifying charge: 30 / (80/100) = 37.5 kWh
    assert result["estimated_usable_kwh"] == pytest.approx(30.0 / 0.80, abs=0.1)


@pytest.mark.asyncio
async def test_lifetime_new_fields_user_isolation(test_sessionmaker):
    """estimated_usable_kwh reflects only the correct user's data."""
    uid_a = await _make_user(test_sessionmaker, "frank")
    uid_b = await _make_user(test_sessionmaker, "grace")
    car_a = await _make_car(test_sessionmaker, uid_a)
    car_b = await _make_car(test_sessionmaker, uid_b)

    # User A: 3 qualifying DC sessions → non-None estimated_usable_kwh
    for when in [dt.date(2026, 1, 1), dt.date(2026, 2, 1), dt.date(2026, 3, 1)]:
        async with test_sessionmaker() as s:
            s.add(
                ChargingSession(
                    user_id=uid_a,
                    car_id=car_a,
                    date=when,
                    start_soc=10,
                    end_soc=80,
                    kwh_added=20.0,
                    charging_type="dc",
                    charging_mode="manual",
                    cost_pence=400,
                    cost_basis="home_rate",
                    source="manual",
                    charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC),
                )
            )
            await s.commit()

    # User B: no sessions

    async with test_sessionmaker() as s:
        result_a = await compute_car_lifetime(s, user_id=uid_a, car_id=car_a)
        result_b = await compute_car_lifetime(s, user_id=uid_b, car_id=car_b)

    assert result_a["estimated_usable_kwh"] is not None
    assert result_b["estimated_usable_kwh"] is None
