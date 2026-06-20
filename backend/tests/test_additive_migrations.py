"""Additive charge-context columns on ChargingSession.

These columns are added idempotently via `_apply_additive_migrations`
for existing databases, and declared on the models so `create_all`
(and the test schema) provisions them on a fresh DB.
"""
import datetime as dt

import pytest

from plugtrack.models import ChargingSession


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
async def test_session_has_actual_charge_seconds(test_sessionmaker, seeded_user_car):
    """actual_charge_seconds stores the real energy-transfer time (vs the
    plug-in window implied by charge_start_at/charge_end_at). Nullable."""
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=dt.date.today(),
            start_soc=60,
            end_soc=90,
            kwh_added=20.0,
            source="import",
            actual_charge_seconds=9 * 3600 + 9 * 60,  # 9h09m
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.actual_charge_seconds == 32940
    # Defaults to NULL when not provided.
    async with test_sessionmaker() as s:
        row2 = ChargingSession(
            user_id=user_id, car_id=car_id, date=dt.date.today(),
            start_soc=20, end_soc=30, kwh_added=5.0, source="manual",
        )
        s.add(row2)
        await s.commit()
        await s.refresh(row2)
        assert row2.actual_charge_seconds is None
