"""Tests for the Setting model."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_setting_round_trip(test_sessionmaker):
    from plugtrack.models import Setting

    async with test_sessionmaker() as session:
        s = Setting(
            key="foo",
            value="bar",
            value_type="string",
            group_name="test",
            label="Foo",
            description="A test setting",
            default_value="bar",
            is_secret=False,
        )
        session.add(s)
        await session.commit()

    async with test_sessionmaker() as session:
        from sqlalchemy import select
        result = await session.execute(select(Setting).where(Setting.key == "foo"))
        loaded = result.scalar_one()
        assert loaded.value == "bar"
        assert loaded.is_secret is False
        assert loaded.updated_at is not None


@pytest.mark.asyncio
async def test_setting_key_is_primary_key(test_sessionmaker):
    from plugtrack.models import Setting
    from sqlalchemy.exc import IntegrityError

    async with test_sessionmaker() as session:
        session.add(Setting(key="dup", value="a", value_type="string", group_name="g", label="L"))
        session.add(Setting(key="dup", value="b", value_type="string", group_name="g", label="L"))
        with pytest.raises(IntegrityError):
            await session.commit()
