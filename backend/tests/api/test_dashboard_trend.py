"""GET /api/dashboard/spend-trend route tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from plugtrack.models import Car, ChargingSession


@pytest.mark.asyncio
async def test_spend_trend_requires_auth(seeded_client):
    r = await seeded_client.get("/api/dashboard/spend-trend")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_spend_trend_returns_window_with_zero_fill(
    authed_client,
    test_sessionmaker,
):
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()

    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
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
        for offset, pence in [(0, 400), (0, 600), (3, 250)]:
            s.add(
                ChargingSession(
                    user_id=user.id,
                    car_id=car.id,
                    date=today - timedelta(days=offset),
                    start_soc=20,
                    end_soc=80,
                    kwh_added=10.0,
                    cost_pence=pence,
                    cost_basis="home_rate",
                    source="manual",
                ),
            )
        await s.commit()

    r = await authed_client.get("/api/dashboard/spend-trend?days=7")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 7

    by_date = {row["date"]: row["cost_pence"] for row in data}
    assert by_date[today.isoformat()] == 1000
    assert by_date[(today - timedelta(days=3)).isoformat()] == 250
    assert by_date[(today - timedelta(days=1)).isoformat()] == 0


@pytest.mark.asyncio
async def test_spend_trend_rejects_invalid_days(authed_client):
    r = await authed_client.get("/api/dashboard/spend-trend?days=0")
    assert r.status_code == 400
    r = await authed_client.get("/api/dashboard/spend-trend?days=1000")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_spend_trend_default_30_days(authed_client):
    r = await authed_client.get("/api/dashboard/spend-trend")
    assert r.status_code == 200
    assert len(r.json()) == 30
