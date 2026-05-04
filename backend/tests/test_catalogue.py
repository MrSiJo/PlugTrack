"""Tests for the settings catalogue and seeding."""
from __future__ import annotations

import pytest
from sqlalchemy import select


def test_catalogue_includes_required_v1_keys():
    from plugtrack.settings.catalogue import CATALOGUE

    keys = {entry.key for entry in CATALOGUE}
    assert "cupra_username" in keys
    assert "cupra_password" in keys
    assert "cupra_spin" in keys
    assert "vehicle_provider" in keys
    assert "sync_interval_minutes_idle" in keys
    assert "sync_interval_minutes_plugged" in keys
    assert "sync_interval_minutes_charging" in keys
    assert "sync_enabled" in keys
    assert "default_home_rate_p_per_kwh" in keys
    assert "petrol_price_p_per_litre" in keys
    assert "petrol_mpg" in keys
    assert "theme" in keys
    assert "currency" in keys
    assert "distance_unit" in keys
    assert "geocoding_enabled" in keys
    assert "geocoding_provider" in keys
    assert "geocoding_api_key" in keys
    assert "location_cluster_radius_m" in keys


def test_cupra_credentials_are_marked_secret():
    from plugtrack.settings.catalogue import CATALOGUE

    by_key = {e.key: e for e in CATALOGUE}
    assert by_key["cupra_username"].is_secret is True
    assert by_key["cupra_password"].is_secret is True
    assert by_key["cupra_spin"].is_secret is True
    assert by_key["theme"].is_secret is False


def test_distance_unit_default_is_miles():
    """UK-default; users in metric markets flip to km via Settings UI."""
    from plugtrack.settings.catalogue import CATALOGUE
    by_key = {e.key: e for e in CATALOGUE}
    assert by_key["distance_unit"].default_value == "mi"


def test_geocoding_api_key_is_marked_secret():
    from plugtrack.settings.catalogue import CATALOGUE
    by_key = {e.key: e for e in CATALOGUE}
    assert by_key["geocoding_api_key"].is_secret is True


@pytest.mark.asyncio
async def test_seed_defaults_inserts_every_catalogue_key(test_sessionmaker):
    from plugtrack.models import Setting
    from plugtrack.settings.catalogue import CATALOGUE
    from plugtrack.settings.seeds import seed_defaults

    async with test_sessionmaker() as session:
        inserted = await seed_defaults(session)
        await session.commit()

    assert inserted == len(CATALOGUE)

    async with test_sessionmaker() as session:
        result = await session.execute(select(Setting))
        rows = result.scalars().all()
        assert len(rows) == len(CATALOGUE)


@pytest.mark.asyncio
async def test_seed_defaults_is_idempotent(test_sessionmaker):
    from plugtrack.settings.seeds import seed_defaults

    async with test_sessionmaker() as session:
        first = await seed_defaults(session)
        await session.commit()

    async with test_sessionmaker() as session:
        second = await seed_defaults(session)
        await session.commit()

    assert first > 0
    assert second == 0


@pytest.mark.asyncio
async def test_seed_defaults_does_not_overwrite_user_values(test_sessionmaker):
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults

    async with test_sessionmaker() as session:
        await seed_defaults(session)
        await session.commit()

    async with test_sessionmaker() as session:
        result = await session.execute(select(Setting).where(Setting.key == "theme"))
        row = result.scalar_one()
        row.value = "dark"
        await session.commit()

    async with test_sessionmaker() as session:
        await seed_defaults(session)
        await session.commit()

    async with test_sessionmaker() as session:
        result = await session.execute(select(Setting).where(Setting.key == "theme"))
        row = result.scalar_one()
        assert row.value == "dark"
