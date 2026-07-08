"""Tests for the settings catalogue and seeding."""

from __future__ import annotations

import pytest
from sqlalchemy import select


def test_catalogue_includes_required_v1_keys():
    from plugtrack.settings.catalogue import CATALOGUE

    keys = {entry.key for entry in CATALOGUE}
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


def test_theme_is_not_secret():
    from plugtrack.settings.catalogue import CATALOGUE

    by_key = {e.key: e for e in CATALOGUE}
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


def test_charge_loss_factor_in_catalogue():
    """charge_loss_factor must be in the catalogue with default '0.90'."""
    from plugtrack.settings.catalogue import CATALOGUE

    by_key = {e.key: e for e in CATALOGUE}
    assert "charge_loss_factor" in by_key
    entry = by_key["charge_loss_factor"]
    assert entry.default_value == "0.90"
    assert entry.value_type == "float"
    assert entry.group_name == "charging"


def test_digest_catalogue_entries_present_with_correct_types():
    """The five digest settings keys must exist with correct types and defaults."""
    from plugtrack.settings.catalogue import CATALOGUE

    by_key = {e.key: e for e in CATALOGUE}

    # digest_weekly_enabled
    assert "digest_weekly_enabled" in by_key
    entry = by_key["digest_weekly_enabled"]
    assert entry.value_type == "bool"
    assert entry.group_name == "telegram"
    assert entry.default_value == "false"
    assert entry.label == "Weekly digest"

    # digest_monthly_enabled
    assert "digest_monthly_enabled" in by_key
    entry = by_key["digest_monthly_enabled"]
    assert entry.value_type == "bool"
    assert entry.group_name == "telegram"
    assert entry.default_value == "false"
    assert entry.label == "Monthly digest"

    # digest_send_hour
    assert "digest_send_hour" in by_key
    entry = by_key["digest_send_hour"]
    assert entry.value_type == "int"
    assert entry.group_name == "telegram"
    assert entry.default_value == "8"
    assert entry.label == "Digest send hour"

    # digest_last_weekly_sent — internal marker, default None
    assert "digest_last_weekly_sent" in by_key
    entry = by_key["digest_last_weekly_sent"]
    assert entry.value_type == "string"
    assert entry.group_name == "telegram"
    assert entry.default_value is None

    # digest_last_monthly_sent — internal marker, default None
    assert "digest_last_monthly_sent" in by_key
    entry = by_key["digest_last_monthly_sent"]
    assert entry.value_type == "string"
    assert entry.group_name == "telegram"
    assert entry.default_value is None


@pytest.mark.asyncio
async def test_seed_defaults_seeds_digest_marker_keys(test_sessionmaker):
    """digest_last_weekly_sent and digest_last_monthly_sent must be seeded
    even though they are hidden from the list endpoint."""
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults

    async with test_sessionmaker() as session:
        await seed_defaults(session)
        await session.commit()

    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "digest_last_weekly_sent")
        )
        row = result.scalar_one_or_none()
        assert row is not None, "digest_last_weekly_sent must be seeded"
        assert row.value is None  # default is None

        result = await session.execute(
            select(Setting).where(Setting.key == "digest_last_monthly_sent")
        )
        row = result.scalar_one_or_none()
        assert row is not None, "digest_last_monthly_sent must be seeded"
        assert row.value is None  # default is None


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
