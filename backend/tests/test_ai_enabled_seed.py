import pytest
from plugtrack.main import reconcile_ai_enabled
from plugtrack.models.setting import Setting
from plugtrack.settings.seeds import seed_defaults  # real module is seeds (plural)
from sqlalchemy import select


@pytest.mark.asyncio
async def test_ai_enabled_seeds_true_when_openai_key_present(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        # Simulate an existing OpenAI key (encrypted value is opaque here).
        row = (await s.execute(select(Setting).where(Setting.key == "openai_api_key"))).scalar_one()
        row.value = "enc:dummy"
        await s.commit()
        await reconcile_ai_enabled(s)
        ai = (await s.execute(select(Setting).where(Setting.key == "ai_enabled"))).scalar_one()
        assert ai.value == "true"


@pytest.mark.asyncio
async def test_ai_enabled_stays_false_without_key(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await reconcile_ai_enabled(s)
        ai = (await s.execute(select(Setting).where(Setting.key == "ai_enabled"))).scalar_one()
        assert ai.value == "false"
