"""Tests for `services/mileage_tracking.py`.

Covers:
- Enable tracking → status reflects opening + computes current odo from
  latest session.
- Anniversary rollover materialises a closing snapshot from the latest
  session at-or-before the period end and opens a new period.
- Multi-year skip: two anniversaries pass without a visit → both
  rollovers materialise on next read.
- Closing falls back to opening when no session data is in-window.
- Target value is copied forward on rollover.
- `clear_tracking` deletes everything.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from plugtrack.models import Car, ChargingSession, User
from plugtrack.services import mileage_tracking
from plugtrack.services.mileage_tracking import KM_PER_MILE


async def _make_user(sessionmaker, username: str = "alice") -> User:
    async with sessionmaker() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _make_car(sessionmaker, user_id: int) -> Car:
    async with sessionmaker() as s:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car


async def _add_session(sessionmaker, *, user_id: int, car_id: int, when: date, odo_km: float) -> None:
    async with sessionmaker() as s:
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=when,
                start_soc=20,
                end_soc=80,
                kwh_added=10.0,
                charging_type="ac",
                charging_mode="manual",
                cost_basis="unknown",
                source="manual",
                odometer_at_session_km=odo_km,
                charge_end_at=datetime.combine(when, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                ),
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_enable_then_status_with_live_current(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)
    # Latest session: Aug 2025, odo 7100 mi (≈ 11425 km).
    await _add_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2026, 1, 15),
        odo_km=10033.0 * KM_PER_MILE,
    )
    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=10000.0,
            today=date(2026, 5, 1),
        )
        await session.commit()

    async with test_sessionmaker() as session:
        status = await mileage_tracking.get_status(
            session,
            user_id=user.id,
            car_id=car.id,
            today=date(2026, 5, 1),
        )

    assert status.enabled is True
    assert status.history == []
    cp = status.current_period
    assert cp is not None
    assert cp.period_start_date == date(2025, 8, 1)
    assert cp.period_end_date == date(2026, 7, 31)
    assert cp.opening_odometer_km == pytest.approx(7022.0 * KM_PER_MILE)
    assert cp.current_odometer_km == pytest.approx(10033.0 * KM_PER_MILE)
    assert cp.annual_mileage_target_km == pytest.approx(10000.0 * KM_PER_MILE)


@pytest.mark.asyncio
async def test_rollover_uses_session_at_or_before_period_end(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    # Inside the first period: a session at 9000 mi on 2026-07-01.
    await _add_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2026, 7, 1),
        odo_km=9000.0 * KM_PER_MILE,
    )
    # AFTER the first period end (2026-07-31): a session at 9500 mi.
    # Must NOT be counted as the closing — that mileage belongs to year 2.
    await _add_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2026, 8, 5),
        odo_km=9500.0 * KM_PER_MILE,
    )

    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=None,
            today=date(2025, 8, 2),  # before any rollover
        )
        await session.commit()

    # Now read with today AFTER the first period end.
    async with test_sessionmaker() as session:
        status = await mileage_tracking.get_status(
            session,
            user_id=user.id,
            car_id=car.id,
            today=date(2026, 8, 10),
        )
        await session.commit()

    assert len(status.history) == 1
    closed = status.history[0]
    assert closed.period_start_date == date(2025, 8, 1)
    assert closed.period_end_date == date(2026, 7, 31)
    # Closing must be from the 2026-07-01 session (9000 mi), not the
    # 2026-08-05 one.
    assert closed.closing_odometer_km == pytest.approx(9000.0 * KM_PER_MILE)

    cp = status.current_period
    assert cp is not None
    assert cp.period_start_date == date(2026, 8, 1)
    assert cp.period_end_date == date(2027, 7, 31)
    assert cp.opening_odometer_km == pytest.approx(9000.0 * KM_PER_MILE)
    # Latest session at-or-before today=2026-08-10 is the 9500 mi one.
    assert cp.current_odometer_km == pytest.approx(9500.0 * KM_PER_MILE)


@pytest.mark.asyncio
async def test_rollover_skips_two_years(test_sessionmaker):
    """When the user doesn't visit for 2+ years, both rollovers fire."""
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    await _add_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2026, 6, 1),
        odo_km=9000.0 * KM_PER_MILE,
    )
    await _add_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2027, 6, 1),
        odo_km=12000.0 * KM_PER_MILE,
    )

    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=10000.0,
            today=date(2025, 8, 2),
        )
        await session.commit()

    async with test_sessionmaker() as session:
        status = await mileage_tracking.get_status(
            session,
            user_id=user.id,
            car_id=car.id,
            today=date(2027, 9, 1),
        )
        await session.commit()

    # Two periods rolled over; one active.
    assert len(status.history) == 2
    history_sorted = sorted(status.history, key=lambda r: r.period_start_date)
    assert history_sorted[0].period_start_date == date(2025, 8, 1)
    assert history_sorted[0].closing_odometer_km == pytest.approx(
        9000.0 * KM_PER_MILE
    )
    assert history_sorted[1].period_start_date == date(2026, 8, 1)
    assert history_sorted[1].closing_odometer_km == pytest.approx(
        12000.0 * KM_PER_MILE
    )
    # Target copied forward.
    for row in history_sorted:
        assert row.annual_mileage_target_km == pytest.approx(
            10000.0 * KM_PER_MILE
        )

    cp = status.current_period
    assert cp is not None
    assert cp.period_start_date == date(2027, 8, 1)
    assert cp.opening_odometer_km == pytest.approx(12000.0 * KM_PER_MILE)
    assert cp.annual_mileage_target_km == pytest.approx(10000.0 * KM_PER_MILE)


@pytest.mark.asyncio
async def test_rollover_with_no_in_window_data_closes_at_opening(
    test_sessionmaker,
):
    """If no sessions exist on/before the period end, closing == opening."""
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=None,
            today=date(2025, 8, 2),
        )
        await session.commit()

    async with test_sessionmaker() as session:
        status = await mileage_tracking.get_status(
            session,
            user_id=user.id,
            car_id=car.id,
            today=date(2026, 9, 1),
        )
        await session.commit()

    assert len(status.history) == 1
    closed = status.history[0]
    assert closed.closing_odometer_km == pytest.approx(7022.0 * KM_PER_MILE)
    cp = status.current_period
    assert cp is not None
    assert cp.opening_odometer_km == pytest.approx(7022.0 * KM_PER_MILE)
    assert cp.current_odometer_km == pytest.approx(7022.0 * KM_PER_MILE)


@pytest.mark.asyncio
async def test_clear_tracking_deletes_everything(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=None,
        )
        await session.commit()

    async with test_sessionmaker() as session:
        await mileage_tracking.clear_tracking(
            session, user_id=user.id, car_id=car.id
        )
        await session.commit()

    async with test_sessionmaker() as session:
        status = await mileage_tracking.get_status(
            session, user_id=user.id, car_id=car.id
        )
    assert status.enabled is False
    assert status.current_period is None
    assert status.history == []


@pytest.mark.asyncio
async def test_set_tracking_replaces_existing_history(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    async with test_sessionmaker() as session:
        await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2024, 1, 1),
            opening_miles=5000.0,
            annual_mileage_target_miles=None,
        )
        await session.commit()

    # Re-enable with different baseline → previous row gone.
    async with test_sessionmaker() as session:
        status = await mileage_tracking.set_tracking(
            session,
            user_id=user.id,
            car_id=car.id,
            start_date=date(2025, 8, 1),
            opening_miles=7022.0,
            annual_mileage_target_miles=None,
        )
        await session.commit()

    assert status.history == []
    assert status.current_period is not None
    assert status.current_period.period_start_date == date(2025, 8, 1)
    assert status.current_period.opening_odometer_km == pytest.approx(
        7022.0 * KM_PER_MILE
    )
