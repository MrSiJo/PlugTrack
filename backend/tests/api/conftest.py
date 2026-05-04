"""Helpers for the API test suite.

Provides:
- `seeded_client`: a client whose app has been booted through its
  lifespan handler, so the `setting` table is populated.
- `authed_client`: a `seeded_client` with a user created and a valid
  signed session cookie set, plus a primed CSRF cookie.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME, make_serializer
from plugtrack.security.csrf import CSRF_COOKIE_NAME
from plugtrack.services.auth_service import bootstrap_user


@pytest_asyncio.fixture
async def seeded_client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            yield c


@pytest_asyncio.fixture
async def authed_client(app, test_sessionmaker):
    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            user = await bootstrap_user(session, "admin", "test-password-12chars")

        serializer = make_serializer("test-secret-key-for-tests-only-padding-padding")
        token = serializer.dumps({"user_id": user.id})

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            c.cookies.set(SESSION_COOKIE_NAME, token)
            # Prime CSRF cookie via a safe request.
            await c.get("/api/health")
            # /api/health is in the CSRF EXEMPT_PATHS — fetch a non-exempt
            # safe route to actually receive a CSRF cookie. Settings GET
            # works because we have a valid session.
            await c.get("/api/settings")
            yield c


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    """Pull the CSRF cookie value off the client and shape it as headers."""
    token = client.cookies.get(CSRF_COOKIE_NAME, "")
    return {"X-CSRF-Token": token}
