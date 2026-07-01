"""Tests for /api/auth/login and /api/auth/logout."""
from __future__ import annotations

import pytest

from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME
from plugtrack.api.login_throttle import login_throttle
from plugtrack.services.auth_service import bootstrap_user
from tests.api.conftest import csrf_headers


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """The throttle is a process-local singleton — isolate it per test."""
    login_throttle.clear()
    yield
    login_throttle.clear()


async def _prime_csrf(client):
    await client.get("/api/health")


@pytest.mark.asyncio
async def test_login_with_valid_credentials_sets_cookie(seeded_client, test_sessionmaker):
    async with test_sessionmaker() as session:
        await bootstrap_user(session, "admin", "very-strong-pass")

    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 200, r.text
    assert SESSION_COOKIE_NAME in r.cookies
    body = r.json()
    assert body["username"] == "admin"


@pytest.mark.asyncio
async def test_login_with_bad_password_returns_401(seeded_client, test_sessionmaker):
    async with test_sessionmaker() as session:
        await bootstrap_user(session, "admin", "very-strong-pass")

    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-wrong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_for_unknown_user_returns_401(seeded_client):
    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_without_csrf_is_403(seeded_client):
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "very-strong-pass"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_login_sets_samesite_strict_cookie(seeded_client, test_sessionmaker):
    async with test_sessionmaker() as session:
        await bootstrap_user(session, "admin", "very-strong-pass")

    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.asyncio
async def test_locked_username_returns_429_with_retry_after(seeded_client, test_sessionmaker):
    async with test_sessionmaker() as session:
        await bootstrap_user(session, "admin", "very-strong-pass")

    # Drive the throttle straight into a locked state, then confirm the route
    # refuses even a correct password with 429 + Retry-After.
    for _ in range(login_throttle.max_failures):
        login_throttle.record_failure("admin")

    await _prime_csrf(seeded_client)
    r = await seeded_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "very-strong-pass"},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 429, r.text
    assert "retry-after" in {k.lower() for k in r.headers.keys()}


@pytest.mark.asyncio
async def test_logout_requires_auth(seeded_client):
    # No session cookie attached → auth middleware 401s.
    r = await seeded_client.post("/api/auth/logout")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie_when_authed(authed_client):
    from tests.api.conftest import csrf_headers

    r = await authed_client.post("/api/auth/logout", headers=csrf_headers(authed_client))
    assert r.status_code == 200
    # set-cookie expiring should appear in headers
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
