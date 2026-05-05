"""GET /api/sessions filter param tests."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from plugtrack.models import Car, ChargingSession, Location


async def _bootstrap(authed_client, test_sessionmaker):
    """Seed two cars and a varied set of sessions for the active user.

    Returns: (user_id, car_a_id, car_b_id, location_id, today)
    """
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()

    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        car_a = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        car_b = Car(
            user_id=user.id,
            make="VW",
            model="ID.4",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.8,
            provider="manual",
            active=True,
        )
        loc = Location(
            user_id=user.id,
            name="Home",
            centroid_lat=51.5,
            centroid_lng=-0.1,
            visit_count=0,
        )
        s.add_all([car_a, car_b, loc])
        await s.commit()
        await s.refresh(car_a)
        await s.refresh(car_b)
        await s.refresh(loc)

        rows = [
            (today, car_a.id, "manual", loc.id),
            (today - timedelta(days=10), car_a.id, "synthesis", None),
            (today - timedelta(days=40), car_a.id, "cariad", loc.id),
            (today - timedelta(days=2), car_b.id, "manual", None),
        ]
        for d, cid, src, lid in rows:
            s.add(
                ChargingSession(
                    user_id=user.id,
                    car_id=cid,
                    date=d,
                    start_soc=20,
                    end_soc=80,
                    kwh_added=10.0,
                    cost_pence=100,
                    cost_basis="home_rate",
                    location_id=lid,
                    source=src,
                ),
            )
        await s.commit()

        return user.id, car_a.id, car_b.id, loc.id, today


@pytest.mark.asyncio
async def test_list_no_filters_returns_all(authed_client, test_sessionmaker):
    await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get("/api/sessions")
    assert r.status_code == 200
    assert len(r.json()) == 4


@pytest.mark.asyncio
async def test_filter_by_car_id(authed_client, test_sessionmaker):
    _, car_a, car_b, _, _ = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_a}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert all(row["car_id"] == car_a for row in rows)


@pytest.mark.asyncio
async def test_filter_by_source(authed_client, test_sessionmaker):
    await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get("/api/sessions?source=manual")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"manual"}


@pytest.mark.asyncio
async def test_filter_by_invalid_source_400(authed_client):
    r = await authed_client.get("/api/sessions?source=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_filter_by_date_range(authed_client, test_sessionmaker):
    _, _, _, _, today = await _bootstrap(authed_client, test_sessionmaker)
    df = (today - timedelta(days=15)).isoformat()
    dt = today.isoformat()
    r = await authed_client.get(
        f"/api/sessions?date_from={df}&date_to={dt}",
    )
    assert r.status_code == 200
    # Excludes the 40-day-old session.
    assert len(r.json()) == 3


@pytest.mark.asyncio
async def test_filter_by_location_id(authed_client, test_sessionmaker):
    _, _, _, loc_id, _ = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?location_id={loc_id}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(row["location_id"] == loc_id for row in rows)


@pytest.mark.asyncio
async def test_combined_filters(authed_client, test_sessionmaker):
    _, car_a, _, _, today = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(
        f"/api/sessions?car_id={car_a}&source=synthesis"
        f"&date_from={(today - timedelta(days=20)).isoformat()}"
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "synthesis"
