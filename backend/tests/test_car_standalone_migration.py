# backend/tests/test_car_standalone_migration.py
"""Existing cupra_connect cars become standalone (provider='manual') on boot."""
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_value_migration_flips_provider(test_engine):
    from plugtrack.main import _apply_value_migrations

    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO car (user_id, make, model, battery_kwh, "
                "nominal_efficiency_mi_per_kwh, provider, active, created_at, updated_at) "
                "VALUES (1, 'Cupra', 'Born', 58.0, 4.2, 'cupra_connect', 1, "
                "'2026-01-01', '2026-01-01')"
            )
        )
    async with test_engine.begin() as conn:
        await _apply_value_migrations(conn)
    async with test_engine.begin() as conn:
        provider = (await conn.execute(text("SELECT provider FROM car"))).scalar_one()
    assert provider == "manual"
