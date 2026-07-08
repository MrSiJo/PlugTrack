# backend/tests/models/test_screenshot_import.py
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_screenshot_import_roundtrip(test_sessionmaker):
    from plugtrack.models import ScreenshotImport, User

    async with test_sessionmaker() as s:
        user = User(username="alice", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)

        row = ScreenshotImport(
            user_id=user.id,
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
