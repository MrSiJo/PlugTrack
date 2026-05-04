"""Tests for the double-submit CSRF middleware."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from plugtrack.security.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    EXEMPT_PATHS,
    CsrfMiddleware,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CsrfMiddleware)

    @app.get("/api/safe")
    async def _safe():
        return {"ok": True}

    @app.post("/api/mutate")
    async def _mutate():
        return {"ok": True}

    @app.post("/api/health")
    async def _health_post():  # exempt
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_get_sets_csrf_cookie():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/safe")
        assert r.status_code == 200
        assert CSRF_COOKIE_NAME in r.cookies


@pytest.mark.asyncio
async def test_post_without_header_is_403():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        await c.get("/api/safe")  # seed cookie
        r = await c.post("/api/mutate")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_with_mismatching_header_is_403():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        await c.get("/api/safe")
        r = await c.post("/api/mutate", headers={CSRF_HEADER_NAME: "wrong-value"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_with_matching_header_is_allowed():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        seed = await c.get("/api/safe")
        token = seed.cookies[CSRF_COOKIE_NAME]
        r = await c.post("/api/mutate", headers={CSRF_HEADER_NAME: token})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_exempt_path_post_works_without_csrf():
    assert "/api/health" in EXEMPT_PATHS
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post("/api/health")
        assert r.status_code == 200, r.text
