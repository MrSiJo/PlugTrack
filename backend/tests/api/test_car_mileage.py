"""API tests for /api/cars/{id}/mileage."""

from __future__ import annotations

import pytest

from tests.api.conftest import csrf_headers

KM_PER_MILE = 1.609344


async def _create_car(authed_client) -> int:
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 4.2,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_get_mileage_starts_disabled(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.get(f"/api/cars/{car_id}/mileage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["current_period"] is None
    assert body["history"] == []


@pytest.mark.asyncio
async def test_put_then_get_mileage(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.put(
        f"/api/cars/{car_id}/mileage",
        json={
            "start_date": "2025-08-01",
            "opening_miles": 7022,
            "annual_mileage_target_miles": 10000,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    cp = body["current_period"]
    assert cp["period_start_date"] == "2025-08-01"
    assert cp["period_end_date"] == "2026-07-31"
    assert cp["opening_odometer_km"] == pytest.approx(7022 * KM_PER_MILE)
    assert cp["annual_mileage_target_km"] == pytest.approx(10000 * KM_PER_MILE)


@pytest.mark.asyncio
async def test_put_mileage_target_optional(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.put(
        f"/api/cars/{car_id}/mileage",
        json={"start_date": "2025-08-01", "opening_miles": 7022},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_period"]["annual_mileage_target_km"] is None


@pytest.mark.asyncio
async def test_delete_mileage(authed_client):
    car_id = await _create_car(authed_client)
    await authed_client.put(
        f"/api/cars/{car_id}/mileage",
        json={"start_date": "2025-08-01", "opening_miles": 7022},
        headers=csrf_headers(authed_client),
    )
    r = await authed_client.delete(
        f"/api/cars/{car_id}/mileage", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 204
    r = await authed_client.get(f"/api/cars/{car_id}/mileage")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_mileage_routes_require_auth(seeded_client):
    r = await seeded_client.get("/api/cars/1/mileage")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_mileage_requires_csrf(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.put(
        f"/api/cars/{car_id}/mileage",
        json={"start_date": "2025-08-01", "opening_miles": 7022},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_mileage_404_for_other_users_car(authed_client):
    """A car id that doesn't belong to the user must 404, not 200."""
    r = await authed_client.get("/api/cars/9999/mileage")
    assert r.status_code == 404
