"""MQTT settings catalogue."""
import pytest
from sqlalchemy import select

from plugtrack.models.setting import Setting
from plugtrack.settings.catalogue import CATALOGUE
from plugtrack.settings.seeds import seed_defaults

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
    assert by_key["mqtt_base_topic"].default_value == "plugtrack"


def test_catalogue_has_no_personal_broker_credentials():
    """PLUG-M5: host/username/password must not ship personal defaults —
    the Admin page requires the user to enter their own broker details."""
    by_key = {e.key: e for e in CATALOGUE}
    assert by_key["mqtt_host"].default_value is None
    assert by_key["mqtt_username"].default_value is None
    assert by_key["mqtt_password"].default_value is None


@pytest.mark.asyncio
async def test_seed_defaults_inserts_mqtt_rows(test_sessionmaker):
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(Setting).where(Setting.key.in_(MQTT_KEYS)))).scalars().all()
    assert {r.key for r in rows} == MQTT_KEYS
    by_key = {r.key: r for r in rows}
    # PLUG-M5: no password (or other credential) is ever seeded.
    assert by_key["mqtt_password"].value is None
    assert by_key["mqtt_host"].value is None
    assert by_key["mqtt_username"].value is None
