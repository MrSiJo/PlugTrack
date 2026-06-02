"""API tests for GET /api/charge-plan.

Uses the authed_client fixture (from tests/api/conftest.py) which gives
a live app with a seeded settings table and a signed session cookie.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from plugtrack.models import Car, ChargingSession, Location, User
from tests.api.conftest import csrf_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_car(client, battery_kwh: float = 77.0) -> int:
    r = await client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": battery_kwh,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _get_user_id(test_sessionmaker) -> int:
    async with test_sessionmaker() as session:
        row = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        return row.id


async def _make_home_location(
    test_sessionmaker,
    user_id: int,
    *,
    is_free: bool = False,
    default_cost_per_kwh_p: float | None = None,
) -> int:
    async with test_sessionmaker() as session:
        loc = Location(
            user_id=user_id,
            name="Home",
            centroid_lat=50.85,
            centroid_lng=-0.13,
            radius_m=100,
            is_home=True,
            is_free=is_free,
            default_cost_per_kwh_p=default_cost_per_kwh_p,
        )
        session.add(loc)
        await session.commit()
        await session.refresh(loc)
        return loc.id


async def _make_ac_session(
    test_sessionmaker,
    user_id: int,
    car_id: int,
    location_id: int,
    kwh_added: float,
    duration_hours: float,
) -> None:
    """Insert a home AC charging session directly into the DB."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=duration_hours)
    async with test_sessionmaker() as session:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            location_id=location_id,
            date=now.date(),
            charge_start_at=start,
            charge_end_at=now,
            start_soc=20,
            end_soc=80,
            kwh_added=kwh_added,
            charging_type="ac",
            charging_mode="timer",
            source="synthesis",
            interrupted=False,
            cost_pence=None,
            cost_basis="unknown",
        )
        session.add(cs)
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_requires_auth(seeded_client):
    r = await seeded_client.get("/api/charge-plan?car_id=1&start_soc=20&target_soc=80")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_charge_plan_happy_path(authed_client):
    """Happy-path: returns the contract shape with all required fields."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Required top-level fields present and typed correctly.
    assert body["car_id"] == car_id
    assert body["start_soc"] == 20
    assert body["target_soc"] == 80
    assert body["battery_kwh"] == 77.0
    assert isinstance(body["kwh_needed"], float)
    assert isinstance(body["power_kw"], float)
    assert body["power_basis"] in ("history", "fallback")
    assert isinstance(body["sample_size"], int)
    assert isinstance(body["total_minutes"], int)
    assert ":" in body["window_start"]
    assert ":" in body["window_end"]
    assert isinstance(body["window_minutes"], int)
    assert isinstance(body["fits_one_window"], bool)
    assert isinstance(body["nights"], list)
    assert len(body["nights"]) >= 1
    assert isinstance(body["nights_needed"], int)
    assert body["nights_needed"] == len(body["nights"])
    assert ":" in body["finish_at"]
    assert isinstance(body["cost_pence"], int)
    assert isinstance(body["home_rate_p_per_kwh"], float)
    assert isinstance(body["is_free"], bool)

    # nights entries have the expected shape.
    for i, n in enumerate(body["nights"], start=1):
        assert n["index"] == i
        assert isinstance(n["minutes"], int)
        assert isinstance(n["end_soc"], int)
        assert ":" in n["finish_at"]


@pytest.mark.asyncio
async def test_charge_plan_fallback_power_path(authed_client):
    """When there are no home AC sessions, power_basis should be 'fallback'."""
    car_id = await _create_car(authed_client)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["power_basis"] == "fallback"
    assert body["sample_size"] == 0
    # Default fallback is 7.4 kW (from catalogue).
    assert body["power_kw"] == 7.4


@pytest.mark.asyncio
async def test_charge_plan_404_unknown_car(authed_client):
    r = await authed_client.get(
        "/api/charge-plan?car_id=99999&start_soc=20&target_soc=80"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_charge_plan_400_target_not_greater_than_start(authed_client):
    car_id = await _create_car(authed_client)
    # target == start
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=50&target_soc=50"
    )
    assert r.status_code == 400

    # target < start
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=80&target_soc=20"
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_charge_plan_soc_validation_422(authed_client):
    """FastAPI should reject SoC values outside 0-100 with 422."""
    car_id = await _create_car(authed_client)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=-1&target_soc=80"
    )
    assert r.status_code == 422

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=101"
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_charge_plan_history_power_path(authed_client, test_sessionmaker):
    """When >= 3 home AC sessions exist, power_basis should be 'history'."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)

    home_loc_id = await _make_home_location(test_sessionmaker, user_id)

    # Insert 3 home AC sessions; each delivers 7.0 kW effective (14 kWh in 2h).
    for _ in range(3):
        await _make_ac_session(
            test_sessionmaker,
            user_id,
            car_id,
            home_loc_id,
            kwh_added=14.0,
            duration_hours=2.0,  # effective = 7.0 kW
        )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["power_basis"] == "history"
    assert body["sample_size"] == 3
    # median effective_kw = 7.0
    assert abs(body["power_kw"] - 7.0) < 0.05


@pytest.mark.asyncio
async def test_charge_plan_is_free_home_location(authed_client, test_sessionmaker):
    """Home location with is_free=True → cost_pence=0, is_free=True."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)
    await _make_home_location(test_sessionmaker, user_id, is_free=True)

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is True
    assert body["cost_pence"] == 0


@pytest.mark.asyncio
async def test_charge_plan_home_location_custom_rate(authed_client, test_sessionmaker):
    """Home location with default_cost_per_kwh_p uses that rate for cost."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)
    await _make_home_location(
        test_sessionmaker, user_id, default_cost_per_kwh_p=28.5
    )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is False
    assert body["home_rate_p_per_kwh"] == 28.5
    expected_cost = round(body["kwh_needed"] * 28.5)
    assert body["cost_pence"] == expected_cost


@pytest.mark.asyncio
async def test_charge_plan_default_home_rate_fallback(authed_client):
    """No home location → uses 'default_home_rate_p_per_kwh' setting (7.5 p)."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is False
    assert body["home_rate_p_per_kwh"] == 7.5
    expected_cost = round(body["kwh_needed"] * 7.5)
    assert body["cost_pence"] == expected_cost


@pytest.mark.asyncio
async def test_charge_plan_kwh_needed_formula(authed_client):
    """kwh_needed == (target-start)/100 * battery_kwh rounded to 2dp."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    body = r.json()
    expected = round((80 - 20) / 100 * 77.0, 2)
    assert abs(body["kwh_needed"] - expected) < 0.005


@pytest.mark.asyncio
async def test_charge_plan_window_minutes_default(authed_client):
    """Default window 23:45→07:15 = 450 minutes."""
    car_id = await _create_car(authed_client)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    body = r.json()
    assert body["window_minutes"] == 450
    assert body["window_start"] == "23:45"
    assert body["window_end"] == "07:15"


@pytest.mark.asyncio
async def test_charge_plan_car_not_owned_by_other_user(authed_client, test_sessionmaker):
    """A car owned by a different user should return 404."""
    # Create a second user and their car directly in DB.
    async with test_sessionmaker() as session:
        from plugtrack.models import User as UserModel
        other = UserModel(username="other_user", password_hash="x")
        session.add(other)
        await session.commit()
        await session.refresh(other)
        other_id = other.id

        car = Car(
            user_id=other_id,
            make="Tesla",
            model="Model 3",
            battery_kwh=75.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)
        other_car_id = car.id

    r = await authed_client.get(
        f"/api/charge-plan?car_id={other_car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 404
