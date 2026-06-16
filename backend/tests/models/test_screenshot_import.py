# backend/tests/models/test_screenshot_import.py
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_screenshot_import_roundtrip(test_sessionmaker):
    from plugtrack.models import ScreenshotImport

    async with test_sessionmaker() as s:
        row = ScreenshotImport(
            user_id=1,
            telegram_file_id="abc",
            image_sha256="deadbeef",
            source="osprey",
            extracted={"energy_kwh": 9.78, "cost_total_pence": 851},
            status="staged",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.id is not None
        assert row.status == "staged"
        got = (await s.execute(select(ScreenshotImport))).scalar_one()
        assert got.extracted["energy_kwh"] == 9.78
