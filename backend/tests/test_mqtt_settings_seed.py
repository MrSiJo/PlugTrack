"""MQTT settings catalogue + encrypted password seed."""
import pytest
from sqlalchemy import select

from plugtrack.models.setting import Setting
from plugtrack.settings.catalogue import CATALOGUE
from plugtrack.settings.seeds import seed_defaults
from plugtrack.main import seed_mqtt_password
from plugtrack.security.crypto import decrypt_secret
from plugtrack.bootstrap import get_settings

MQTT_KEYS = {
    "mqtt_enabled",
    "mqtt_host",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "mqtt_base_topic",
}


def test_catalogue_defines_mqtt_group():
    by_key = {e.key: e for e in CATALOGUE}
    for k in MQTT_KEYS:
        assert k in by_key, f"missing catalogue key {k}"
        assert by_key[k].group_name == "mqtt"
    assert by_key["mqtt_password"].is_secret is True
    assert by_key["mqtt_enabled"].default_value == "true"
    assert by_key["mqtt_port"].default_value == "1883"
    assert by_key["mqtt_username"].default_value == "oil"
    assert by_key["mqtt_base_topic"].default_value == "plugtrack"


@pytest.mark.asyncio
async def test_seed_defaults_inserts_mqtt_rows(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(Setting).where(Setting.key.in_(MQTT_KEYS)))).scalars().all()
    assert {r.key for r in rows} == MQTT_KEYS


@pytest.mark.asyncio
async def test_seed_mqtt_password_encrypts_when_unset(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
    async with test_sessionmaker() as s:
        await seed_mqtt_password(s)  # commits internally
    async with test_sessionmaker() as s:
        row = (await s.execute(select(Setting).where(Setting.key == "mqtt_password"))).scalar_one()
    assert row.value is not None
    assert row.value != "oil"  # stored ciphertext, not plaintext
    assert decrypt_secret(row.value, get_settings().app_secret_key) == "oil"


@pytest.mark.asyncio
async def test_seed_mqtt_password_is_idempotent_and_non_destructive(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
    # user set their own password first
    async with test_sessionmaker() as s:
        row = (await s.execute(select(Setting).where(Setting.key == "mqtt_password"))).scalar_one()
        row.value = "user-choice-ciphertext"
        await s.commit()
    async with test_sessionmaker() as s:
        await seed_mqtt_password(s)
    async with test_sessionmaker() as s:
        row = (await s.execute(select(Setting).where(Setting.key == "mqtt_password"))).scalar_one()
    assert row.value == "user-choice-ciphertext"  # untouched
