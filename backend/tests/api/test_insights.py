"""Tests for GET /api/insights/by-location."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from plugtrack.models import Location, User
from tests.api.conftest import csrf_headers


async def _create_car(client) -> int:
    r = await client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born", "battery_kwh": 77.0,
              "nominal_efficiency_mi_per_kwh": 3.6},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _user_id(test_sessionmaker) -> int:
    async with test_sessionmaker() as s:
        return (await s.execute(select(User).where(User.username == "admin"))).scalar_one().id


async def _make_location(test_sessionmaker, user_id, **kw) -> int:
    defaults = dict(centroid_lat=50.85, centroid_lng=-0.13, radius_m=100, visit_count=0)
    defaults.update(kw)
    async with test_sessionmaker() as s:
        loc = Location(user_id=user_id, **defaults)
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
        return loc.id


@pytest.mark.asyncio
async def test_by_location_requires_auth(seeded_client):
    r = await seeded_client.get("/api/insights/by-location")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_by_location_shape_and_totals(authed_client, test_sessionmaker):
    uid = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _make_location(test_sessionmaker, uid, name="Home", default_cost_per_kwh_p=10.0)
    for kwh in (10.0, 20.0):
        r = await authed_client.post(
            "/api/sessions",
            json={"car_id": car_id, "date": date.today().isoformat(),
                  "start_soc": 20, "end_soc": 80, "kwh_added": kwh, "location_id": loc_id},
            headers=csrf_headers(authed_client),
        )
        assert r.status_code == 201, r.text

    r = await authed_client.get("/api/insights/by-location")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"rows", "totals"}
    assert body["totals"]["sessions"] == 2
    assert body["totals"]["spend_pence"] == round(10.0 * 10.0) + round(20.0 * 10.0)
    [home] = [row for row in body["rows"] if row["location_id"] == loc_id]
    assert home["name"] == "Home"
    assert home["avg_p_per_kwh"] == pytest.approx(10.0)
    assert home["pct_of_spend"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Task 12: car_id filter on /overview and /by-location
# ---------------------------------------------------------------------------

async def _make_car(client, make="Cupra", model="Born") -> int:
    r = await client.post(
        "/api/cars",
        json={"make": make, "model": model, "battery_kwh": 77.0,
              "nominal_efficiency_mi_per_kwh": 3.6},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _post_session(client, *, car_id, kwh, cost_pence=None, ctype="ac", date_str=None):
    from datetime import date as date_cls
    date_str = date_str or date_cls.today().isoformat()
    body = {
        "car_id": car_id,
        "date": date_str,
        "start_soc": 20,
        "end_soc": 80,
        "kwh_added": kwh,
        "charging_type": ctype,
    }
    if cost_pence is not None:
        body["total_cost_pence_override"] = cost_pence
    r = await client.post("/api/sessions", json=body, headers=csrf_headers(client))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_overview_car_id_filter(authed_client):
    """GET /api/insights/overview?car_id=X returns only X's sessions."""
    car1 = await _make_car(authed_client, model="Born")
    car2 = await _make_car(authed_client, model="Formentor")

    await _post_session(authed_client, car_id=car1, kwh=10.0, cost_pence=200, ctype="ac")
    await _post_session(authed_client, car_id=car2, kwh=40.0, cost_pence=800, ctype="dc")

    r = await authed_client.get(f"/api/insights/overview?car_id={car1}")
    assert r.status_code == 200, r.text
    body = r.json()

    # Only car1's session should appear
    total_kwh = sum(p["kwh"] for p in body["over_time"])
    assert total_kwh == pytest.approx(10.0)

    # Split should show only AC (car1's ctype)
    assert body["split"]["home"]["sessions"] == 1  # ac = home
    assert body["split"]["public"]["sessions"] == 0


@pytest.mark.asyncio
async def test_by_location_car_id_filter(authed_client, test_sessionmaker):
    """GET /api/insights/by-location?car_id=X scopes aggregates to that car."""
    uid = await _user_id(test_sessionmaker)
    car1 = await _make_car(authed_client, model="Born")
    car2 = await _make_car(authed_client, model="Formentor")
    loc_id = await _make_location(test_sessionmaker, uid, name="Home", default_cost_per_kwh_p=10.0)

    await _post_session(authed_client, car_id=car1, kwh=10.0, cost_pence=100)
    await _post_session(authed_client, car_id=car2, kwh=20.0, cost_pence=200)

    r = await authed_client.get(f"/api/insights/by-location?car_id={car1}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["sessions"] == 1
    assert body["totals"]["spend_pence"] == 100
