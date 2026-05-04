"""Tests for POST /api/setup."""
from __future__ import annotations

import pytest

from tests.api.conftest import csrf_headers


async def _prime_csrf(client):
    await client.get("/api/health")


@pytest.mark.asyncio
async def test_setup_creates_first_user(seeded_client):
    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/setup",
        json={"username": "admin", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "admin"
    assert isinstance(body["user_id"], int)


@pytest.mark.asyncio
async def test_setup_rejects_short_password(seeded_client):
    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/setup",
        json={"username": "admin", "password": "short"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_setup_second_call_refused(seeded_client):
    await _prime_csrf(seeded_client)
    r1 = await seeded_client.post(
        "/api/setup",
        json={"username": "admin", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r1.status_code == 201, r1.text

    r2 = await seeded_client.post(
        "/api/setup",
        json={"username": "second", "password": "another-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_setup_without_csrf_is_403(seeded_client):
    r = await seeded_client.post(
        "/api/setup",
        json={"username": "admin", "password": "very-strong-pass"},
    )
    assert r.status_code == 403
