"""Tests for `dashboard_trend.compute_spend_trend`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from plugtrack.models import Car, ChargingSession, User
from plugtrack.services.dashboard_trend import compute_spend_trend


async def _make_user(sessionmaker, username: str) -> User:
    async with sessionmaker() as s:
        u = User(username=username, password_hash="x")
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def _make_car(sessionmaker, user_id: int) -> Car:
    async with sessionmaker() as s:
        c = Car(
            user_id=user_id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c


async def _make_session(
    sessionmaker,
    *,
    user_id: int,
    car_id: int,
    when: date,
    cost_pence: int | None,
) -> None:
    async with sessionmaker() as s:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=when,
            kwh_added=10.0,
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence is not None else "unknown",
            start_soc=20,
            end_soc=80,
            source="manual",
        )
        s.add(cs)
        await s.commit()


@pytest.mark.asyncio
async def test_empty_returns_zero_filled_window(test_sessionmaker) -> None:
    user = await _make_user(test_sessionmaker, "alice")
    today = date(2026, 5, 5)

    async with test_sessionmaker() as s:
        result = await compute_spend_trend(s, user_id=user.id, days=7, today=today)

    assert len(result) == 7
    assert result[0].date == date(2026, 4, 29)
    assert result[-1].date == today
    assert all(d.cost_pence == 0 for d in result)


@pytest.mark.asyncio
async def test_aggregates_multi_session_days(test_sessionmaker) -> None:
    user = await _make_user(test_sessionmaker, "alice")
    car = await _make_car(test_sessionmaker, user.id)
    today = date(2026, 5, 5)

    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today,
        cost_pence=400,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today,
        cost_pence=600,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today - timedelta(days=2),
        cost_pence=250,
    )

    async with test_sessionmaker() as s:
        result = await compute_spend_trend(s, user_id=user.id, days=7, today=today)

    assert {d.date: d.cost_pence for d in result} == {
        today - timedelta(days=6): 0,
        today - timedelta(days=5): 0,
        today - timedelta(days=4): 0,
        today - timedelta(days=3): 0,
        today - timedelta(days=2): 250,
        today - timedelta(days=1): 0,
        today: 1000,
    }


@pytest.mark.asyncio
async def test_excludes_other_users(test_sessionmaker) -> None:
    alice = await _make_user(test_sessionmaker, "alice")
    bob = await _make_user(test_sessionmaker, "bob")
    alice_car = await _make_car(test_sessionmaker, alice.id)
    bob_car = await _make_car(test_sessionmaker, bob.id)
    today = date(2026, 5, 5)

    await _make_session(
        test_sessionmaker,
        user_id=alice.id,
        car_id=alice_car.id,
        when=today,
        cost_pence=300,
    )
    await _make_session(
        test_sessionmaker,
        user_id=bob.id,
        car_id=bob_car.id,
        when=today,
        cost_pence=900,
    )

    async with test_sessionmaker() as s:
        result = await compute_spend_trend(s, user_id=alice.id, days=3, today=today)

    assert sum(d.cost_pence for d in result) == 300


@pytest.mark.asyncio
async def test_ignores_sessions_outside_window(test_sessionmaker) -> None:
    user = await _make_user(test_sessionmaker, "alice")
    car = await _make_car(test_sessionmaker, user.id)
    today = date(2026, 5, 5)

    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today - timedelta(days=10),
        cost_pence=999,
    )

    async with test_sessionmaker() as s:
        result = await compute_spend_trend(s, user_id=user.id, days=7, today=today)

    assert all(d.cost_pence == 0 for d in result)


@pytest.mark.asyncio
async def test_treats_null_cost_as_zero(test_sessionmaker) -> None:
    user = await _make_user(test_sessionmaker, "alice")
    car = await _make_car(test_sessionmaker, user.id)
    today = date(2026, 5, 5)

    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today,
        cost_pence=None,
    )

    async with test_sessionmaker() as s:
        result = await compute_spend_trend(s, user_id=user.id, days=3, today=today)

    assert result[-1].cost_pence == 0
