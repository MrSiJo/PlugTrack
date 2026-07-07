"""Payload builder + publish tick for the Home Assistant MQTT bridge."""
import datetime as dt

import pytest

from plugtrack.models.charging_session import ChargingSession
from plugtrack.services.ha_publisher import build_ha_payload


@pytest.mark.asyncio
async def test_build_payload_shape_and_unit_conversion(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    today = dt.date(2026, 7, 15)
    async with test_sessionmaker() as s:
        from plugtrack.models.location import Location
        loc = Location(
            user_id=user_id,
            name="Osprey (Land's End)",
            centroid_lat=50.065,
            centroid_lng=-5.715,
        )
        s.add(loc)
        await s.flush()
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=dt.date(2026, 7, 6),
                charge_end_at=dt.datetime(2026, 7, 6, 21, 14, tzinfo=dt.timezone.utc),
                start_soc=40,
                kwh_added=41.2,
                cost_pence=824,          # £8.24
                cost_basis="location_rate",
                end_soc=82,
                charge_network="Osprey",
                location_id=loc.id,
                source="manual",
                odometer_at_session_km=19875.0,  # ~12350 mi
            )
        )
        await s.commit()

    async with test_sessionmaker() as s:
        payload = await build_ha_payload(s, user_id=user_id, today=today)

    assert payload is not None
    # last charge
    assert payload["last_charge"]["kwh"] == pytest.approx(41.2)
    assert payload["last_charge"]["cost_gbp"] == pytest.approx(8.24)
    assert payload["last_charge"]["network"] == "Osprey"
    assert payload["last_charge"]["location"] == "Osprey (Land's End)"  # resolved via JOIN
    assert payload["last_charge"]["end_soc_pct"] == 82
    assert payload["last_charge"]["ts"].startswith("2026-07-06T21:14")
    # battery + odometer converted km -> mi
    assert payload["battery_soc_pct"] == 82
    assert payload["odometer_mi"] == pytest.approx(12350, abs=5)
    # groups present
    assert set(payload["month"]) >= {"spend_gbp", "energy_kwh", "miles", "home_pct", "public_pct"}
    assert set(payload["lifetime"]) >= {"energy_kwh", "cost_gbp"}
    assert "annual_mileage" in payload


@pytest.mark.asyncio
async def test_build_payload_none_when_no_cars(test_sessionmaker):
    # a user with no active car -> nothing to publish
    from plugtrack.models.user import User
    async with test_sessionmaker() as s:
        u = User(username="carless", password_hash="x")
        s.add(u)
        await s.commit()
        uid = u.id
    async with test_sessionmaker() as s:
        payload = await build_ha_payload(s, user_id=uid, today=dt.date(2026, 7, 15))
    assert payload is None
