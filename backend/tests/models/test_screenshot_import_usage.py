import pytest
from sqlalchemy import select, text


@pytest.mark.asyncio
async def test_usage_columns_roundtrip(test_sessionmaker):
    from plugtrack.models import ScreenshotImport

    async with test_sessionmaker() as s:
        row = ScreenshotImport(
            user_id=1,
            image_sha256="abc",
            source="osprey",
            extracted={},
            status="staged",
            input_tokens=2400,
            output_tokens=410,
            reasoning_tokens=0,
        )
        s.add(row)
        await s.commit()
        got = (await s.execute(select(ScreenshotImport))).scalar_one()
        assert got.input_tokens == 2400 and got.output_tokens == 410 and got.reasoning_tokens == 0


@pytest.mark.asyncio
async def test_additive_migration_idempotent(test_engine):
    from plugtrack.main import _apply_additive_migrations

    async with test_engine.begin() as conn:
        await _apply_additive_migrations(conn)
        await _apply_additive_migrations(conn)  # second run must not error
    async with test_engine.begin() as conn:
        cols = {
            r[1] for r in (await conn.execute(text("PRAGMA table_info(screenshot_import)"))).all()
        }
    assert {"input_tokens", "output_tokens", "reasoning_tokens"} <= cols
