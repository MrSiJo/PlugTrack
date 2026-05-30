"""Additive charge-context columns on ChargingSession + CarStateSnapshot.

These columns are added idempotently via `_apply_additive_migrations`
for existing databases, and declared on the models so `create_all`
(and the test schema) provisions them on a fresh DB.
"""
import datetime as dt

import pytest

from plugtrack.models import CarStateSnapshot, ChargingSession


@pytest.mark.asyncio
async def test_session_has_context_columns(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=dt.date.today(),
            start_soc=20,
            end_soc=80,
            kwh_added=10.0,
            source="synthesis",
            charging_mode="timer",
            battery_care=True,
            max_charge_current="maximum",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.battery_care is True
        assert row.max_charge_current == "maximum"


@pytest.mark.asyncio
async def test_car_state_has_live_context_columns(test_sessionmaker, seeded_user_car):
    _uid, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = CarStateSnapshot(
            car_id=car_id,
            last_battery_care=True,
            last_max_charge_current="reduced",
            last_charging_estimated_end_at=dt.datetime.now(dt.timezone.utc),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.last_max_charge_current == "reduced"
