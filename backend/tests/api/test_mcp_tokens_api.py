"""Tests for /api/mcp/tokens — mint, list, revoke.

TDD: these tests are written against the yet-to-exist route module.
Run `pytest tests/api/test_mcp_tokens_api.py -v` to see RED first.
"""
from __future__ import annotations

import pytest

from tests.api.conftest import csrf_headers


# ---------------------------------------------------------------------------
# Unauthenticated (no cookie) — 401 on every method.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tokens_requires_auth(seeded_client):
    r = await seeded_client.get("/api/mcp/tokens")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_token_requires_auth(seeded_client):
    r = await seeded_client.post(
        "/api/mcp/tokens",
        json={"name": "My Client", "scope": "read"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_token_requires_auth(seeded_client):
    r = await seeded_client.delete("/api/mcp/tokens/1")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# CSRF check — POST / DELETE without the CSRF header → 403.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_token_requires_csrf(authed_client):
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "My Client", "scope": "read"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_token_requires_csrf(authed_client):
    r = await authed_client.delete("/api/mcp/tokens/1")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Happy-path — mint a token, list it, revoke it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_returns_plaintext_once(authed_client):
    """POST returns the plaintext token in the response body."""
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Claude Desktop", "scope": "readwrite"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "token" in body, "plaintext token must be in the mint response"
    assert "id" in body
    assert body["name"] == "Claude Desktop"
    assert body["scope"] == "readwrite"
    assert "created_at" in body
    # Sanity: token looks like a URL-safe b64 string (no whitespace, non-empty)
    assert len(body["token"]) > 20
    assert " " not in body["token"]


@pytest.mark.asyncio
async def test_list_never_returns_token_or_hash(authed_client):
    """GET /api/mcp/tokens must never expose the plaintext token or hash."""
    # First mint one.
    await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Test Token", "scope": "read"},
        headers=csrf_headers(authed_client),
    )

    r = await authed_client.get("/api/mcp/tokens")
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert isinstance(tokens, list)
    assert len(tokens) >= 1

    for tok in tokens:
        assert "token" not in tok, "list must NOT return plaintext token"
        assert "token_hash" not in tok, "list must NOT return token_hash"
        # Expected safe fields only
        assert "id" in tok
        assert "name" in tok
        assert "scope" in tok
        assert "created_at" in tok
        assert "last_used_at" in tok


@pytest.mark.asyncio
async def test_revoke_deletes_the_token(authed_client):
    """DELETE removes the token; subsequent list is empty."""
    # Mint.
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Revokable", "scope": "read"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    token_id = r.json()["id"]

    # List — should have one.
    r = await authed_client.get("/api/mcp/tokens")
    assert len(r.json()) == 1

    # Revoke.
    r = await authed_client.delete(
        f"/api/mcp/tokens/{token_id}",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 204, r.text

    # List — should be empty.
    r = await authed_client.get("/api/mcp/tokens")
    assert r.json() == []


# ---------------------------------------------------------------------------
# Cross-user isolation — user cannot revoke another user's token.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_cannot_revoke_other_users_token(app, authed_client, other_user_headers):
    """Revoking another user's token returns 404."""
    from httpx import ASGITransport, AsyncClient
    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME
    from plugtrack.security.csrf import CSRF_COOKIE_NAME

    # Authed user mints a token.
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Mine", "scope": "read"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201
    token_id = r.json()["id"]

    # 'other_user' tries to delete via a fresh client (own cookie jar, own CSRF).
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as other_client:
        other_client.cookies.set(SESSION_COOKIE_NAME, other_user_headers[SESSION_COOKIE_NAME])
        # Prime CSRF by fetching a safe endpoint.
        await other_client.get("/api/settings")
        csrf = other_client.cookies.get(CSRF_COOKIE_NAME, "")
        r = await other_client.delete(
            f"/api/mcp/tokens/{token_id}",
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Validation — invalid scope → 400.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_scope_returns_400(authed_client):
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Bad Scope", "scope": "write"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_read_scope_accepted(authed_client):
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Reader", "scope": "read"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    assert r.json()["scope"] == "read"


@pytest.mark.asyncio
async def test_readwrite_scope_accepted(authed_client):
    r = await authed_client.post(
        "/api/mcp/tokens",
        json={"name": "Writer", "scope": "readwrite"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    assert r.json()["scope"] == "readwrite"


# ---------------------------------------------------------------------------
# 404 on unknown token.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_unknown_token_returns_404(authed_client):
    r = await authed_client.delete(
        "/api/mcp/tokens/99999",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 404, r.text
