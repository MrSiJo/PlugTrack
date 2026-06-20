"""The new standalone/ingestion settings must exist in the catalogue and seed."""
import pytest

from plugtrack.settings.catalogue import CATALOGUE
from plugtrack.settings.seeds import seed_defaults

NEW_KEYS = {
    "telegram_bot_enabled": ("bool", False),
    "telegram_bot_token": ("string", True),
    "telegram_allowed_user_ids": ("string", False),
    "telegram_default_car_id": ("int", False),
    "openai_api_key": ("string", True),
    "openai_model": ("string", False),
}


def test_new_keys_present_with_expected_flags():
    by_key = {e.key: e for e in CATALOGUE}
    for key, (vtype, is_secret) in NEW_KEYS.items():
        assert key in by_key, f"{key} missing from catalogue"
        assert by_key[key].value_type == vtype, key
        assert by_key[key].is_secret is is_secret, key


def test_ingestion_defaults():
    by_key = {e.key: e for e in CATALOGUE}
    assert by_key["telegram_bot_enabled"].default_value == "false"
    assert by_key["openai_model"].default_value == "gpt-5.5"


@pytest.mark.asyncio
async def test_seed_inserts_new_keys(test_sessionmaker):
    from sqlalchemy import select
    from plugtrack.models import Setting

    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
        rows = {r.key for r in (await s.execute(select(Setting))).scalars().all()}
    for key in NEW_KEYS:
        assert key in rows
