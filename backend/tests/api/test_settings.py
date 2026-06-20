"""Tests for /api/settings routes."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from plugtrack.models import Setting
from plugtrack.security.crypto import decrypt_secret
from plugtrack.settings.catalogue import CATALOGUE
from tests.api.conftest import csrf_headers


@pytest.mark.asyncio
async def test_get_settings_requires_auth(seeded_client):
    r = await seeded_client.get("/api/settings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_settings_returns_catalogue_keys(authed_client):
    r = await authed_client.get("/api/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    expected_keys = {entry.key for entry in CATALOGUE}
    assert set(body.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_settings_redacts_secrets(authed_client, test_sessionmaker):
    # Set a non-null value on a known secret key, then verify the GET hides it.
    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "openai_api_key")
        )
        row = result.scalar_one()
        row.value = "ciphertext-doesnt-matter"
        await session.commit()

    r = await authed_client.get("/api/settings")
    body = r.json()
    assert body["openai_api_key"]["value"] == "***"
    assert body["openai_api_key"]["is_secret"] is True
    # Non-secret entries pass through.
    assert body["currency"]["value"] == "GBP"
    assert body["currency"]["is_secret"] is False


@pytest.mark.asyncio
async def test_get_settings_redacts_secret_even_when_db_row_misflagged(
    authed_client, test_sessionmaker
):
    # Defence-in-depth: even if `is_secret` on the row was flipped to
    # False, the catalogue lookup is the source of truth and it stays
    # redacted on read.
    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "openai_api_key")
        )
        row = result.scalar_one()
        row.value = "should-stay-hidden"
        row.is_secret = False  # tampered
        await session.commit()

    r = await authed_client.get("/api/settings")
    body = r.json()
    assert body["openai_api_key"]["value"] == "***"
    assert body["openai_api_key"]["is_secret"] is True


@pytest.mark.asyncio
async def test_put_setting_requires_auth(seeded_client):
    r = await seeded_client.put(
        "/api/settings", json={"key": "currency", "value": "EUR"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_setting_requires_csrf(authed_client):
    r = await authed_client.put(
        "/api/settings", json={"key": "currency", "value": "EUR"}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_setting_updates_value(authed_client, test_sessionmaker):
    r = await authed_client.put(
        "/api/settings",
        json={"key": "currency", "value": "EUR"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "currency")
        )
        row = result.scalar_one()
        assert row.value == "EUR"


@pytest.mark.asyncio
async def test_put_setting_rejects_unknown_key(authed_client):
    r = await authed_client.put(
        "/api/settings",
        json={"key": "not-in-catalogue", "value": "x"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_setting_encrypts_secret(authed_client, test_sessionmaker):
    plain = "super-secret-password"
    r = await authed_client.put(
        "/api/settings",
        json={"key": "openai_api_key", "value": plain},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text

    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "openai_api_key")
        )
        row = result.scalar_one()
        # Stored value is ciphertext (not the plaintext) and decrypts back.
        assert row.value is not None
        assert row.value != plain
        decrypted = decrypt_secret(
            row.value, "test-secret-key-for-tests-only-padding-padding"
        )
        assert decrypted == plain


@pytest.mark.asyncio
async def test_catalogue_has_ai_keys_grouped(test_sessionmaker):
    from plugtrack.settings.catalogue import CATALOGUE
    by_key = {e.key: e for e in CATALOGUE}
    assert "ai_enabled" in by_key
    assert by_key["ai_enabled"].value_type == "bool"
    assert by_key["ai_enabled"].group_name == "ai"
    assert "ai_provider" in by_key
    assert by_key["ai_provider"].value_type == "enum"
    assert by_key["ai_provider"].default_value == "openai"
    # openai_* regrouped under "ai" so the AI integration card can find them
    for k in ("openai_api_key", "openai_model",
              "openai_input_price_per_1k_pence", "openai_output_price_per_1k_pence"):
        assert by_key[k].group_name == "ai", f"{k} not regrouped"
