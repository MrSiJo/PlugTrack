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
            select(Setting).where(Setting.key == "cupra_password")
        )
        row = result.scalar_one()
        row.value = "ciphertext-doesnt-matter"
        await session.commit()

    r = await authed_client.get("/api/settings")
    body = r.json()
    assert body["cupra_password"]["value"] == "***"
    assert body["cupra_password"]["is_secret"] is True
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
            select(Setting).where(Setting.key == "cupra_password")
        )
        row = result.scalar_one()
        row.value = "should-stay-hidden"
        row.is_secret = False  # tampered
        await session.commit()

    r = await authed_client.get("/api/settings")
    body = r.json()
    assert body["cupra_password"]["value"] == "***"
    assert body["cupra_password"]["is_secret"] is True


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
        json={"key": "cupra_password", "value": plain},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text

    async with test_sessionmaker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == "cupra_password")
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
async def test_clear_pycupra_tokens_requires_auth(seeded_client):
    r = await seeded_client.post("/api/settings/clear-pycupra-tokens")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_clear_pycupra_tokens_requires_csrf(authed_client):
    r = await authed_client.post("/api/settings/clear-pycupra-tokens")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_clear_pycupra_tokens_returns_count(authed_client, tmp_path, monkeypatch):
    # Point the route at a tmp_path-backed dir.
    from plugtrack.api.routes import settings as settings_module

    fake_dir = tmp_path / "pycupra"
    fake_dir.mkdir()
    (fake_dir / "tokens.json").write_text("{}")
    (fake_dir / "auth.cache").write_text("nope")

    monkeypatch.setattr(settings_module, "_pycupra_dir", lambda: fake_dir)

    r = await authed_client.post(
        "/api/settings/clear-pycupra-tokens",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cleared"] is True
    assert body["count"] == 2
    assert list(fake_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_clear_pycupra_tokens_no_dir_returns_zero(
    authed_client, tmp_path, monkeypatch
):
    from plugtrack.api.routes import settings as settings_module

    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(settings_module, "_pycupra_dir", lambda: missing)

    r = await authed_client.post(
        "/api/settings/clear-pycupra-tokens",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"cleared": False, "count": 0}
