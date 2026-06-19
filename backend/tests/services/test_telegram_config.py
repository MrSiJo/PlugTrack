# backend/tests/services/test_telegram_config.py
import pytest
from sqlalchemy import select


async def _seed(test_sessionmaker, **overrides):
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    from plugtrack.security.crypto import encrypt_secret
    from plugtrack.bootstrap import get_settings
    get_settings.cache_clear()
    secret = get_settings().app_secret_key
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        vals = {
            "telegram_bot_enabled": "true",
            "telegram_bot_token": encrypt_secret("tok", secret),
            "openai_api_key": encrypt_secret("sk-x", secret),
            "openai_model": "gpt-5-mini",
            "telegram_allowed_user_ids": "111",
            "telegram_default_car_id": None,  # set below from the seeded car
        }
        vals.update(overrides)
        rows = {r.key: r for r in (await s.execute(select(Setting))).scalars().all()}
        for k, v in vals.items():
            if v is not None:
                rows[k].value = v
        await s.commit()


@pytest.mark.asyncio
async def test_problem_when_no_car(test_sessionmaker):
    from plugtrack.services.telegram_ingest import load_bot_config, ConfigProblem
    await _seed(test_sessionmaker)
    cfg = await load_bot_config(test_sessionmaker)
    assert isinstance(cfg, ConfigProblem)
    assert any("car" in r.lower() for r in cfg.reasons)


@pytest.mark.asyncio
async def test_problem_when_disabled(test_sessionmaker, seeded_user_car):
    from plugtrack.services.telegram_ingest import load_bot_config, ConfigProblem
    user_id, car_id = seeded_user_car
    await _seed(test_sessionmaker, telegram_bot_enabled="false",
                telegram_default_car_id=str(car_id))
    cfg = await load_bot_config(test_sessionmaker)
    assert isinstance(cfg, ConfigProblem)
    assert any("disabled" in r.lower() for r in cfg.reasons)


@pytest.mark.asyncio
async def test_valid_config(test_sessionmaker, seeded_user_car):
    from plugtrack.services.telegram_ingest import load_bot_config, BotConfig
    user_id, car_id = seeded_user_car
    await _seed(test_sessionmaker, telegram_default_car_id=str(car_id))
    cfg = await load_bot_config(test_sessionmaker)
    assert isinstance(cfg, BotConfig)
    assert cfg.token == "tok" and cfg.openai_key == "sk-x"
    assert cfg.model == "gpt-5-mini" and cfg.allowed == {111}
    assert cfg.car_id == car_id and cfg.user_id == user_id


@pytest.mark.asyncio
async def test_ai_enabled_true(test_sessionmaker, seeded_user_car):
    from plugtrack.services.telegram_ingest import load_bot_config, BotConfig
    _user_id, car_id = seeded_user_car
    await _seed(test_sessionmaker, telegram_default_car_id=str(car_id), ai_enabled="true")
    cfg = await load_bot_config(test_sessionmaker)
    assert isinstance(cfg, BotConfig)
    assert cfg.ai_enabled is True


@pytest.mark.asyncio
async def test_ai_enabled_false(test_sessionmaker, seeded_user_car):
    from plugtrack.services.telegram_ingest import load_bot_config, BotConfig
    _user_id, car_id = seeded_user_car
    await _seed(test_sessionmaker, telegram_default_car_id=str(car_id), ai_enabled="false")
    cfg = await load_bot_config(test_sessionmaker)
    assert isinstance(cfg, BotConfig)
    assert cfg.ai_enabled is False
