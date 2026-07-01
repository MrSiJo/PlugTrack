from __future__ import annotations

import datetime as dt

import pytest

from plugtrack.models import Car, ChargingSession, User
from sqlalchemy import select


async def _seed_car_and_session(sm, *, when, kwh, cost_pence, ctype="ac", network=None, odometer_km=None):
    async with sm() as s:
        user = (await s.execute(select(User))).scalar_one()
        car = Car(user_id=user.id, make="Cupra", model="Born", battery_kwh=58.0,
                  nominal_efficiency_mi_per_kwh=4.2, provider="manual", active=True)
        s.add(car)
        await s.commit()
        await s.refresh(car)
        s.add(ChargingSession(
            user_id=user.id, car_id=car.id, date=when, start_soc=20, end_soc=80,
            kwh_added=kwh, charging_type=ctype, charging_mode="manual",
            cost_pence=cost_pence, cost_basis="home_rate", charge_network=network,
            source="manual", odometer_at_session_km=odometer_km))
        await s.commit()
        return user.id, car.id


@pytest.mark.asyncio
async def test_overview_requires_auth(seeded_client):
    r = await seeded_client.get("/api/insights/overview")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_overview_shape(authed_client, test_sessionmaker):
    await _seed_car_and_session(test_sessionmaker, when=dt.date(2026, 6, 2), kwh=30.0, cost_pence=1500, ctype="dc", network="Tesla")
    r = await authed_client.get("/api/insights/overview?date_from=2026-06-01&date_to=2026-06-30")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["granularity"] == "daily"
    assert data["over_time"] == [{"period": "2026-06-02", "spend_pence": 1500, "kwh": 30.0, "sessions": 1}]
    assert data["split"]["public"]["spend_pence"] == 1500
    assert data["by_network"][0]["network"] == "Tesla"
    assert "efficiency" in data
    # battery_health is always present (None when no qualifying charges / no car).
    assert "battery_health" in data


@pytest.mark.asyncio
async def test_overview_granularity_resolves_from_window(authed_client, test_sessionmaker):
    await _seed_car_and_session(test_sessionmaker, when=dt.date(2026, 3, 1), kwh=10.0, cost_pence=200)
    r = await authed_client.get("/api/insights/overview?date_from=2026-01-01&date_to=2026-06-30")
    assert r.status_code == 200, r.text
    assert r.json()["granularity"] == "weekly"  # 181-day window


@pytest.mark.asyncio
async def test_mileage_endpoint(authed_client, test_sessionmaker):
    uid, car = await _seed_car_and_session(
        test_sessionmaker, when=dt.date(2026, 4, 10), kwh=10.0, cost_pence=100,
        odometer_km=12000.0 * 1.609344)
    from plugtrack.services import mileage_tracking
    async with test_sessionmaker() as s:
        await mileage_tracking.set_tracking(
            s, user_id=uid, car_id=car, start_date=dt.date(2026, 1, 1),
            opening_miles=10000.0, annual_mileage_target_miles=10000.0, today=dt.date(2026, 1, 1))
        await s.commit()
    r = await authed_client.get(f"/api/insights/mileage?car_id={car}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is True
    assert data["car_id"] == car
    assert data["days_total"] == 365


@pytest.mark.asyncio
async def test_mileage_endpoint_not_enabled(authed_client, test_sessionmaker):
    uid, car = await _seed_car_and_session(test_sessionmaker, when=dt.date(2026, 4, 10), kwh=10.0, cost_pence=100)
    r = await authed_client.get(f"/api/insights/mileage?car_id={car}")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "enabled": False, "car_id": car, "period_start": None, "period_end": None,
        "opening_km": None, "current_km": None, "target_km": None, "used_km": None,
        "remaining_km": None, "days_elapsed": None, "days_total": None,
        "projected_year_end_km": None, "pace": None,
    }
