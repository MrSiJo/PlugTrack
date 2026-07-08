"""GET /api/dashboard — auth-gated end-to-end check.

Verifies:
- 401 without auth.
- 200 with the seeded user; payload shape matches DashboardSummary.
"""

from __future__ import annotations

from datetime import date

import pytest
from plugtrack.models import Car, ChargingSession


@pytest.mark.asyncio
async def test_dashboard_requires_auth(seeded_client):
    r = await seeded_client.get("/api/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_returns_summary_payload(authed_client, test_sessionmaker):
    # Fetch the bootstrapped user id so we can attach a car + session.
    from plugtrack.models import User
    from sqlalchemy import select

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
        cs = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date(2026, 5, 1),
            start_soc=20,
            end_soc=80,
            kwh_added=15.0,
            charging_type="ac",
            charging_mode="manual",
            cost_pence=120,
            cost_basis="home_rate",
            tariff_p_per_kwh=8.0,
            source="manual",
        )
        s.add(cs)
        await s.commit()

    r = await authed_client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    assert "cars" in data and isinstance(data["cars"], list)
    assert "recent_sessions" in data
    assert "lifetime_totals" in data
    assert "top_locations" in data

    assert len(data["cars"]) == 1
    panel = data["cars"][0]
    assert panel["make"] == "Cupra"
    # Battery snapshot comes from the latest session's end_soc.
    assert "battery_level" in panel
    assert "last_connected" in panel
    assert "mileage_year" in panel
    assert data["lifetime_totals"]["sessions_count"] == 1
    assert data["lifetime_totals"]["kwh"] == pytest.approx(15.0)
    assert data["lifetime_totals"]["cost_pence"] == 120
