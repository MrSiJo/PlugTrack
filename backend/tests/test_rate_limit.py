"""Tests for the slowapi rate limiter."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.datastructures import Headers

from plugtrack.api.rate_limit import client_ip_key, limiter


class _FakeRequest:
    """Minimal stand-in exposing the .client.host and .headers a key needs."""

    def __init__(self, peer: str, xff: str | None = None):
        self.client = type("_C", (), {"host": peer})()
        self.headers = Headers({"x-forwarded-for": xff} if xff else {})


def test_client_ip_key_trusts_forwarded_for_from_private_proxy():
    """Behind nginx (private peer), the real client IP comes from XFF left-most."""
    req = _FakeRequest("172.18.0.5", xff="8.8.8.8, 172.18.0.5")
    assert client_ip_key(req) == "8.8.8.8"


def test_client_ip_key_ignores_forwarded_for_from_public_peer():
    """A direct hit on the published port cannot spoof its IP via XFF."""
    req = _FakeRequest("8.8.8.8", xff="10.0.0.1")
    assert client_ip_key(req) == "8.8.8.8"


def test_client_ip_key_falls_back_to_peer_without_forwarded_header():
    req = _FakeRequest("8.8.8.8")
    assert client_ip_key(req) == "8.8.8.8"


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
