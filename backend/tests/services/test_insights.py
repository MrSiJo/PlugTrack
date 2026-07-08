"""Unit tests for the by-location insights aggregation service."""

from __future__ import annotations

from datetime import date

import pytest
from plugtrack.models import Car, ChargingSession, Location, User
from plugtrack.services.insights import aggregate_by_location


async def _seed_user(test_sessionmaker, username: str) -> int:
    """Create a user row directly (bootstrap_user is single-user-only)."""
    async with test_sessionmaker() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _add_car(test_sessionmaker, user_id: int) -> int:
    async with test_sessionmaker() as s:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Born",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


async def _add_location(test_sessionmaker, user_id: int, **kw) -> int:
    defaults = dict(
        centroid_lat=50.0,
        centroid_lng=0.0,
        radius_m=100,
        visit_count=0,
    )
    defaults.update(kw)
    async with test_sessionmaker() as s:
        loc = Location(user_id=user_id, **defaults)
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
        return loc.id


async def _add_session(
    test_sessionmaker,
    user_id: int,
    car_id: int,
    *,
    location_id: int | None,
    kwh: float,
    cost_pence: int | None,
    d: str = "2026-06-01",
) -> None:
    async with test_sessionmaker() as s:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            location_id=location_id,
            date=date.fromisoformat(d),
            start_soc=20,
            end_soc=80,
            kwh_added=kwh,
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence is not None else "unknown",
            source="manual",
        )
        s.add(cs)
        await s.commit()


@pytest.mark.asyncio
async def test_aggregates_spend_kwh_sessions_and_avg_excludes_unknown_cost(
    test_sessionmaker,
):
    uid = await _seed_user(test_sessionmaker, "admin")
    car = await _add_car(test_sessionmaker, uid)
    loc = await _add_location(test_sessionmaker, uid, name="Home", is_home=True)
    # Two costed sessions + one unknown-cost session at the same location.
    await _add_session(test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=100)
    await _add_session(test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=300)
    await _add_session(test_sessionmaker, uid, car, location_id=loc, kwh=5.0, cost_pence=None)

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(s, user_id=uid, date_from=None, date_to=None)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.location_id == loc
    assert row.name == "Home"
    assert row.is_home is True
    assert row.spend_pence == 400  # 100 + 300; unknown excluded from spend
    assert row.kwh == pytest.approx(25.0)  # all kWh incl. unknown-cost session
    assert row.sessions == 3
    # avg excludes the unknown-cost session: 400 / (10 + 10) = 20.0 p/kWh
    assert row.avg_p_per_kwh == pytest.approx(20.0)
    assert row.pct_of_spend == pytest.approx(100.0)
    assert result.totals == {"spend_pence": 400, "kwh": pytest.approx(25.0), "sessions": 3}


@pytest.mark.asyncio
async def test_unassigned_rollup_and_pct_split(test_sessionmaker):
    uid = await _seed_user(test_sessionmaker, "admin")
    car = await _add_car(test_sessionmaker, uid)
    loc = await _add_location(test_sessionmaker, uid, name="Public", default_cost_per_kwh_p=30.0)
    await _add_session(test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=300)
    # Untagged session → Unassigned row.
    await _add_session(test_sessionmaker, uid, car, location_id=None, kwh=10.0, cost_pence=100)

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(s, user_id=uid, date_from=None, date_to=None)

    by_id = {r.location_id: r for r in result.rows}
    assert by_id[loc].spend_pence == 300
    assert by_id[loc].pct_of_spend == pytest.approx(75.0)
    # Unassigned row present, non-clickable (location_id None), name None.
    assert None in by_id
    assert by_id[None].name is None
    assert by_id[None].spend_pence == 100
    assert by_id[None].pct_of_spend == pytest.approx(25.0)
    assert result.totals["spend_pence"] == 400


@pytest.mark.asyncio
async def test_zero_session_location_listed_with_nulls(test_sessionmaker):
    uid = await _seed_user(test_sessionmaker, "admin")
    await _add_location(test_sessionmaker, uid, name="Never used")

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(s, user_id=uid, date_from=None, date_to=None)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.name == "Never used"
    assert row.spend_pence == 0
    assert row.kwh == pytest.approx(0.0)
    assert row.sessions == 0
    assert row.avg_p_per_kwh is None
    assert row.pct_of_spend == pytest.approx(0.0)
    assert row.first_at is None and row.last_at is None


@pytest.mark.asyncio
async def test_date_window_bounds_rows(test_sessionmaker):
    uid = await _seed_user(test_sessionmaker, "admin")
    car = await _add_car(test_sessionmaker, uid)
    loc = await _add_location(test_sessionmaker, uid, name="Home")
    await _add_session(
        test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=100, d="2026-01-01"
    )
    await _add_session(
        test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=200, d="2026-06-01"
    )

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(
            s, user_id=uid, date_from=date(2026, 5, 1), date_to=date(2026, 6, 30)
        )

    by_id = {r.location_id: r for r in result.rows}
    assert by_id[loc].sessions == 1  # only the June session
    assert by_id[loc].spend_pence == 200


@pytest.mark.asyncio
async def test_user_isolation(test_sessionmaker):
    uid = await _seed_user(test_sessionmaker, "admin")
    other = await _seed_user(test_sessionmaker, "intruder")
    car = await _add_car(test_sessionmaker, other)
    loc = await _add_location(test_sessionmaker, other, name="Theirs")
    await _add_session(test_sessionmaker, other, car, location_id=loc, kwh=10.0, cost_pence=100)

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(s, user_id=uid, date_from=None, date_to=None)

    assert result.rows == []
    assert result.totals == {"spend_pence": 0, "kwh": 0.0, "sessions": 0}


@pytest.mark.asyncio
async def test_labelled_location_with_only_out_of_window_sessions_listed_with_zeros(
    test_sessionmaker,
):
    uid = await _seed_user(test_sessionmaker, "admin")
    car = await _add_car(test_sessionmaker, uid)
    loc = await _add_location(test_sessionmaker, uid, name="Home")
    await _add_session(
        test_sessionmaker, uid, car, location_id=loc, kwh=10.0, cost_pence=100, d="2026-01-01"
    )

    async with test_sessionmaker() as s:
        result = await aggregate_by_location(
            s, user_id=uid, date_from=date(2026, 5, 1), date_to=date(2026, 6, 30)
        )

    by_id = {r.location_id: r for r in result.rows}
    assert loc in by_id
    assert by_id[loc].sessions == 0
    assert by_id[loc].spend_pence == 0
    assert by_id[loc].kwh == 0.0
    assert by_id[loc].avg_p_per_kwh is None


@pytest.mark.asyncio
async def test_aggregate_by_location_car_id_filter(test_sessionmaker):
    """aggregate_by_location with car_id only counts that car's sessions."""
    uid = await _seed_user(test_sessionmaker, "admin")
    car1 = await _add_car(test_sessionmaker, uid)
    car2 = await _add_car(test_sessionmaker, uid)
    loc = await _add_location(test_sessionmaker, uid, name="Home", is_home=True)

    # car1: 10 kWh, 200p at loc; car2: 40 kWh, 800p at same loc
    await _add_session(test_sessionmaker, uid, car1, location_id=loc, kwh=10.0, cost_pence=200)
    await _add_session(test_sessionmaker, uid, car2, location_id=loc, kwh=40.0, cost_pence=800)

    async with test_sessionmaker() as s:
        car1_result = await aggregate_by_location(
            s, user_id=uid, date_from=None, date_to=None, car_id=car1
        )
        both_result = await aggregate_by_location(s, user_id=uid, date_from=None, date_to=None)

    by_id_car1 = {r.location_id: r for r in car1_result.rows}
    assert by_id_car1[loc].sessions == 1
    assert by_id_car1[loc].kwh == pytest.approx(10.0)
    assert by_id_car1[loc].spend_pence == 200

    by_id_both = {r.location_id: r for r in both_result.rows}
    assert by_id_both[loc].sessions == 2
    assert by_id_both[loc].kwh == pytest.approx(50.0)
    assert by_id_both[loc].spend_pence == 1000
