"""Tests for the session-cookie auth middleware."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from plugtrack.api.auth_middleware import (
    EXEMPT_PATHS,
    SESSION_COOKIE_NAME,
    AuthMiddleware,
    make_serializer,
)


SECRET = "x" * 48


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, secret_key=SECRET)

    @app.get("/api/health")
    async def _health():
        return {"ok": True}

    @app.get("/api/private")
    async def _private(request: Request):
        return {"user_id": request.state.user_id}

    return app


@pytest.mark.asyncio
async def test_exempt_path_works_unauthenticated():
    assert "/api/health" in EXEMPT_PATHS
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/health")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_exempt_path_returns_401_without_cookie():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/private")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_non_exempt_path_returns_200_with_valid_cookie():
    serializer = make_serializer(SECRET)
    token = serializer.dumps({"user_id": 1})
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.cookies.set(SESSION_COOKIE_NAME, token)
        r = await c.get("/api/private")
        assert r.status_code == 200
        assert r.json() == {"user_id": 1}


@pytest.mark.asyncio
async def test_tampered_cookie_returns_401():
    serializer = make_serializer(SECRET)
    token = serializer.dumps({"user_id": 1})
    # Tamper by flipping the last char
    bad = token[:-1] + ("a" if token[-1] != "a" else "b")
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.cookies.set(SESSION_COOKIE_NAME, bad)
        r = await c.get("/api/private")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_cookie_signed_with_other_secret_returns_401():
    other = make_serializer("y" * 48)
    token = other.dumps({"user_id": 1})
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.cookies.set(SESSION_COOKIE_NAME, token)
        r = await c.get("/api/private")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_expired_cookie_returns_401():
    """PLUG-L2: sessions expire server-side via the timed serializer."""
    app = FastAPI()
    # max_age_seconds=-1 → any token (age >= 0) is already expired.
    app.add_middleware(AuthMiddleware, secret_key=SECRET, max_age_seconds=-1)

    @app.get("/api/private")
    async def _private(request: Request):
        return {"user_id": request.state.user_id}

    token = make_serializer(SECRET).dumps({"user_id": 1})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.cookies.set(SESSION_COOKIE_NAME, token)
        r = await c.get("/api/private")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_legacy_untimed_cookie_returns_401():
    """A pre-L2 cookie (URLSafeSerializer, no timestamp) is rejected —
    the user just logs in again once."""
    from itsdangerous import URLSafeSerializer

    legacy = URLSafeSerializer(SECRET, salt="session").dumps({"user_id": 1})
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.cookies.set(SESSION_COOKIE_NAME, legacy)
        r = await c.get("/api/private")
        assert r.status_code == 401
