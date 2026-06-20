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


# ---------------------------------------------------------------------------
# Task 2: ownership-trends keys on /overview
# ---------------------------------------------------------------------------

async def _post_session_full(
    client,
    *,
    car_id: int,
    kwh: float,
    start_soc: int,
    end_soc: int,
    ctype: str = "dc",
    date_str: str,
    odometer_km: float | None = None,
):
    """Post a charging session with SoC fields (needed for capacity_trend)."""
    from datetime import date as date_cls
    body = {
        "car_id": car_id,
        "date": date_str,
        "start_soc": start_soc,
        "end_soc": end_soc,
        "kwh_added": kwh,
        "charging_type": ctype,
    }
    if odometer_km is not None:
        body["odometer_at_session_km"] = odometer_km
    r = await client.post("/api/sessions", json=body, headers=csrf_headers(client))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_overview_includes_seasonal_efficiency_and_capacity_trend(authed_client):
    """GET /overview?car_id=X returns non-empty seasonal_efficiency + capacity_trend."""
    # Car with battery_kwh=58.0
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born", "battery_kwh": 58.0,
              "nominal_efficiency_mi_per_kwh": 4.0},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    # Two sessions in different months with large SoC delta (≥40pp) for capacity_trend
    # and odometer data for efficiency_by_month
    await _post_session_full(
        authed_client, car_id=car_id, kwh=20.0,
        start_soc=10, end_soc=80,   # 70pp delta → qualifies
        ctype="dc", date_str="2026-01-15",
        odometer_km=1000.0,
    )
    await _post_session_full(
        authed_client, car_id=car_id, kwh=18.0,
        start_soc=20, end_soc=90,   # 70pp delta → qualifies
        ctype="dc", date_str="2026-03-20",
        odometer_km=1200.0,
    )
    # Third session in yet another month
    await _post_session_full(
        authed_client, car_id=car_id, kwh=15.0,
        start_soc=30, end_soc=80,   # 50pp delta → qualifies
        ctype="dc", date_str="2026-05-10",
        odometer_km=1400.0,
    )

    r = await authed_client.get(f"/api/insights/overview?car_id={car_id}")
    assert r.status_code == 200, r.text
    body = r.json()

    # New keys must be present
    assert "seasonal_efficiency" in body, "Missing seasonal_efficiency key"
    assert "capacity_trend" in body, "Missing capacity_trend key"

    # seasonal_efficiency should have entries (one per month with sessions)
    assert len(body["seasonal_efficiency"]) >= 1
    for pt in body["seasonal_efficiency"]:
        assert "period" in pt
        assert "mi_per_kwh" in pt
        assert "derived_range_km" in pt
        assert "low_confidence" in pt

    # capacity_trend should have qualifying entries
    assert len(body["capacity_trend"]) >= 1
    for pt in body["capacity_trend"]:
        assert "date" in pt
        assert "usable_kwh" in pt
        assert "charging_type" in pt
        assert "low_confidence" in pt

    # Existing keys must remain unchanged
    for key in ("granularity", "over_time", "split", "by_network", "efficiency"):
        assert key in body, f"Existing key '{key}' missing from /overview response"


@pytest.mark.asyncio
async def test_overview_no_car_id_resolves_to_first_active_car(authed_client):
    """GET /overview with no car_id uses the user's first active car for trends."""
    # Create two cars — first active, second also active
    r1 = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born", "battery_kwh": 58.0,
              "nominal_efficiency_mi_per_kwh": 4.0},
        headers=csrf_headers(authed_client),
    )
    assert r1.status_code == 201
    car_id_first = r1.json()["id"]

    r2 = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Formentor", "battery_kwh": 58.0,
              "nominal_efficiency_mi_per_kwh": 4.0},
        headers=csrf_headers(authed_client),
    )
    assert r2.status_code == 201

    # Add qualifying sessions ONLY for the first car (multi-month)
    await _post_session_full(
        authed_client, car_id=car_id_first, kwh=20.0,
        start_soc=10, end_soc=80, ctype="dc", date_str="2026-01-15",
    )
    await _post_session_full(
        authed_client, car_id=car_id_first, kwh=18.0,
        start_soc=20, end_soc=80, ctype="dc", date_str="2026-03-20",
    )
    await _post_session_full(
        authed_client, car_id=car_id_first, kwh=15.0,
        start_soc=25, end_soc=80, ctype="dc", date_str="2026-05-10",
    )

    r = await authed_client.get("/api/insights/overview")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "seasonal_efficiency" in body
    assert "capacity_trend" in body

    # Should reflect first car's data (not empty, since first car has sessions)
    assert len(body["capacity_trend"]) >= 1


@pytest.mark.asyncio
async def test_overview_no_active_car_returns_empty_trend_arrays(authed_client):
    """GET /overview with no car_id and no active cars returns empty trend arrays."""
    # Don't create any cars — user has no active cars
    r = await authed_client.get("/api/insights/overview")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "seasonal_efficiency" in body
    assert "capacity_trend" in body
    assert body["seasonal_efficiency"] == []
    assert body["capacity_trend"] == []

    # Other keys still present
    for key in ("granularity", "over_time", "split", "by_network", "efficiency"):
        assert key in body


# ---------------------------------------------------------------------------
# Fix 2: seasonal_delta wired into /overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_seasonal_delta_none_with_insufficient_data(authed_client):
    """seasonal_delta is None when fewer than 2 months with non-None mi_per_kwh."""
    # Single session → single month → seasonal_delta must be None
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born", "battery_kwh": 58.0,
              "nominal_efficiency_mi_per_kwh": 4.0},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201
    car_id = r.json()["id"]

    # One session — only one month of seasonal data
    await _post_session_full(
        authed_client, car_id=car_id, kwh=20.0,
        start_soc=10, end_soc=80, ctype="dc", date_str="2026-01-15",
        odometer_km=1000.0,
    )

    r = await authed_client.get(f"/api/insights/overview?car_id={car_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "seasonal_delta" in body, "seasonal_delta key must be present"
    assert body["seasonal_delta"] is None


@pytest.mark.asyncio
async def test_overview_seasonal_delta_populated_with_two_months(authed_client):
    """seasonal_delta has best/worst/pct/abs_mi_per_kwh when ≥2 months with mi_per_kwh."""
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born", "battery_kwh": 58.0,
              "nominal_efficiency_mi_per_kwh": 4.0},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201
    car_id = r.json()["id"]

    # Three sessions in different months, with odometer so mi_per_kwh is computed
    await _post_session_full(
        authed_client, car_id=car_id, kwh=20.0,
        start_soc=10, end_soc=80, ctype="dc", date_str="2026-01-15",
        odometer_km=1000.0,
    )
    await _post_session_full(
        authed_client, car_id=car_id, kwh=18.0,
        start_soc=20, end_soc=90, ctype="dc", date_str="2026-03-20",
        odometer_km=1200.0,
    )
    await _post_session_full(
        authed_client, car_id=car_id, kwh=15.0,
        start_soc=30, end_soc=80, ctype="dc", date_str="2026-05-10",
        odometer_km=1400.0,
    )

    r = await authed_client.get(f"/api/insights/overview?car_id={car_id}")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "seasonal_delta" in body, "seasonal_delta key must be present"
    delta = body["seasonal_delta"]
    # Should be populated (≥2 months have mi_per_kwh from odometer data)
    assert delta is not None, "seasonal_delta should be non-None with 3 months of data"
    assert "best" in delta
    assert "worst" in delta
    assert "pct" in delta
    assert "abs_mi_per_kwh" in delta
    assert delta["pct"] >= 0
    assert delta["abs_mi_per_kwh"] >= 0
    assert delta["best"]["mi_per_kwh"] >= delta["worst"]["mi_per_kwh"]
