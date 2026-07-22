from __future__ import annotations

import datetime as dt

import pytest
from plugtrack.models import Car, ChargingSession, Setting, User
from plugtrack.services import mileage_tracking
from plugtrack.services.mileage_tracking import KM_PER_MILE
from plugtrack.services.road_tax import EvedProjection, eved_projection


async def _seed(sm, *, odometer_miles: float, when: dt.date):
    """User + Car + one odometer-bearing session. Returns (user_id, car_id)."""
    async with sm() as s:
        user = User(username="alice", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        s.add(
            ChargingSession(
                user_id=user.id,
                car_id=car.id,
                date=when,
                start_soc=20,
                end_soc=80,
                kwh_added=10.0,
                charging_type="ac",
                charging_mode="manual",
                cost_pence=100,
                cost_basis="home_rate",
                source="manual",
                odometer_at_session_km=odometer_miles * KM_PER_MILE,
            )
        )
        await s.commit()
        return user.id, car.id


async def _set_tracking(sm, user_id, car_id, *, start, opening_miles, target_miles):
    async with sm() as s:
        await mileage_tracking.set_tracking(
            s,
            user_id=user_id,
            car_id=car_id,
            start_date=start,
            opening_miles=opening_miles,
            annual_mileage_target_miles=target_miles,
            today=start,
        )
        await s.commit()


async def _set(sm, key, value):
    async with sm() as s:
        s.add(Setting(key=key, value=value, value_type="string", group_name="eved", label=key))
        await s.commit()


@pytest.mark.asyncio
async def test_returns_none_without_tracking(test_sessionmaker):
    uid, car = await _seed(test_sessionmaker, odometer_miles=11000, when=dt.date(2026, 2, 1))
    async with test_sessionmaker() as s:
        result = await eved_projection(s, user_id=uid, car_id=car, today=dt.date(2026, 6, 1))
    assert result is None


@pytest.mark.asyncio
async def test_running_and_projected_use_default_rate(test_sessionmaker):
    # Tracking opens 2026-01-01 at 10,000 mi; latest odo reading = 11,000 mi.
    # today = 2026-01-101? Use a 100-day-in window: 2026-04-11 (day 101 of 365).
    uid, car = await _seed(test_sessionmaker, odometer_miles=11000, when=dt.date(2026, 3, 1))
    await _set_tracking(
        test_sessionmaker,
        uid,
        car,
        start=dt.date(2026, 1, 1),
        opening_miles=10000,
        target_miles=6000,
    )
    today = dt.date(2026, 4, 11)  # days_elapsed = 101, days_total = 365
    async with test_sessionmaker() as s:
        r = await eved_projection(s, user_id=uid, car_id=car, today=today)
    assert isinstance(r, EvedProjection)
    assert r.rate_p_per_mile == 3.0
    # used = 1,000 mi so far → running = 1000 * 3p = 3000p
    assert r.running_miles == pytest.approx(1000.0, abs=0.5)
    assert r.running_pence == pytest.approx(3000.0, abs=2.0)
    # projected annual miles = 1000 / 101 * 365 ≈ 3614.9 → projected ≈ 10844.6p
    assert r.projected_annual_miles == pytest.approx(1000.0 / 101 * 365, abs=1.0)
    assert r.projected_pence == pytest.approx(r.projected_annual_miles * 3.0, abs=1.0)
    # VED default £200 → 20000p; total = projected + ved
    assert r.ved_pence == pytest.approx(20000.0)
    assert r.total_due_pence == pytest.approx(r.projected_pence + 20000.0, abs=1.0)
    assert r.renewal_date == "07-31"
    assert r.low_confidence is False


@pytest.mark.asyncio
async def test_settings_override_changes_figures(test_sessionmaker):
    uid, car = await _seed(test_sessionmaker, odometer_miles=11000, when=dt.date(2026, 3, 1))
    await _set_tracking(
        test_sessionmaker,
        uid,
        car,
        start=dt.date(2026, 1, 1),
        opening_miles=10000,
        target_miles=6000,
    )
    await _set(test_sessionmaker, "eved_rate_p_per_mile", "1.5")
    await _set(test_sessionmaker, "ved_annual_cost_gbp", "0")
    await _set(test_sessionmaker, "ved_renewal_date", "04-01")
    async with test_sessionmaker() as s:
        r = await eved_projection(s, user_id=uid, car_id=car, today=dt.date(2026, 4, 11))
    assert r.rate_p_per_mile == 1.5
    assert r.running_pence == pytest.approx(1000.0 * 1.5, abs=2.0)
    assert r.ved_pence == pytest.approx(0.0)
    assert r.total_due_pence == pytest.approx(r.projected_pence, abs=1.0)
    assert r.renewal_date == "04-01"


@pytest.mark.asyncio
async def test_low_confidence_when_few_days_elapsed(test_sessionmaker):
    uid, car = await _seed(test_sessionmaker, odometer_miles=10200, when=dt.date(2026, 1, 3))
    await _set_tracking(
        test_sessionmaker,
        uid,
        car,
        start=dt.date(2026, 1, 1),
        opening_miles=10000,
        target_miles=6000,
    )
    async with test_sessionmaker() as s:
        r = await eved_projection(s, user_id=uid, car_id=car, today=dt.date(2026, 1, 5))
    assert r.low_confidence is True  # days_elapsed = 5 (< 14)
