"""Tests for the slowapi rate limiter."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from plugtrack.api.rate_limit import limiter


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/limited")
    @limiter.limit("5/minute")
    async def _limited(request: Request, response: Response):  # noqa: ARG001
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_sixth_request_within_a_minute_is_429_with_retry_after():
    limiter.reset()
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(5):
            r = await client.get("/limited")
            assert r.status_code == 200, r.text

        sixth = await client.get("/limited")
        assert sixth.status_code == 429
        assert "retry-after" in {k.lower() for k in sixth.headers.keys()}
