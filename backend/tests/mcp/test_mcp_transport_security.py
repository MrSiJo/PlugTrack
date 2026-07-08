"""Tests for the /mcp transport-security (DNS-rebinding) configuration.

mcp >= 1.23 validates the Host header on streamable-HTTP transports and
answers HTTP 421 for anything not allowlisted. PlugTrack's policy
(see plugtrack/mcp/server.py:_transport_security_settings):

- MCP_ALLOWED_HOSTS unset/empty  -> protection explicitly DISABLED
  (LAN / reverse-proxy default; /mcp is bearer-token guarded anyway).
- MCP_ALLOWED_HOSTS=<hosts>      -> strict validation with that allowlist.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from plugtrack.bootstrap import get_settings
from plugtrack.mcp.server import _transport_security_settings
from plugtrack.models import User

_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_MCP_URL = "/mcp/"


def _init_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.0.1"},
        },
    }


async def _mint_token(sm) -> str:
    """Seed a user and mint a real read-scope MCPToken, returning plaintext."""
    from plugtrack.services import mcp_tokens

    async with sm() as s:
        user = User(username="sec_user", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        _row, plaintext = await mcp_tokens.mint(s, user_id=user.id, name="sec", scope="read")
    return plaintext


# ---------------------------------------------------------------------------
# Unit: settings construction
# ---------------------------------------------------------------------------


def test_default_disables_dns_rebinding_protection(monkeypatch):
    """Unset MCP_ALLOWED_HOSTS -> protection explicitly disabled.

    This must be an explicit TransportSecuritySettings object: if FastMCP
    receives None it auto-enables a localhost-only allowlist (its default
    host is 127.0.0.1), which would 421 any reverse-proxied Host.
    """
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    get_settings.cache_clear()
    settings = _transport_security_settings()
    assert settings is not None
    assert settings.enable_dns_rebinding_protection is False


def test_allowlist_enables_strict_validation_and_expands_bare_hosts(monkeypatch):
    """Comma-separated env -> strict mode; bare hosts also match any port."""
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "plugtrack.lan, localhost,127.0.0.1:9278, [::1]:*")
    get_settings.cache_clear()
    settings = _transport_security_settings()
    assert settings.enable_dns_rebinding_protection is True
    # Bare entries expand to both the port-less form and a :* wildcard,
    # because the SDK's exact-match "host:*" does NOT match bare "host".
    assert "plugtrack.lan" in settings.allowed_hosts
    assert "plugtrack.lan:*" in settings.allowed_hosts
    assert "localhost" in settings.allowed_hosts
    assert "localhost:*" in settings.allowed_hosts
    # Entries with an explicit port / wildcard / IPv6 colon pass verbatim.
    assert "127.0.0.1:9278" in settings.allowed_hosts
    assert "[::1]:*" in settings.allowed_hosts
    assert "127.0.0.1:9278:*" not in settings.allowed_hosts


# ---------------------------------------------------------------------------
# End-to-end: default app serves any Host (reverse-proxied FQDN keeps working)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_mode_serves_arbitrary_host_header(app, test_sessionmaker):
    """Out of the box (no MCP_ALLOWED_HOSTS), a reverse-proxied internal FQDN
    Host header must NOT be answered with 421."""
    token = await _mint_token(test_sessionmaker)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        # nosec B113 — in-process ASGI transport, no network I/O to time out.
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:  # nosec B113
            headers = dict(_RPC_HEADERS)
            headers["Authorization"] = f"Bearer {token}"
            headers["Host"] = "plugtrack.internal.example.lan"
            r = await c.post(_MCP_URL, json=_init_payload(), headers=headers)
            assert r.status_code != 421, f"421 for proxied Host; body: {r.text[:300]}"
            assert r.status_code < 400, f"unexpected {r.status_code}: {r.text[:300]}"


# ---------------------------------------------------------------------------
# End-to-end: strict mode 421s disallowed Hosts, serves allowlisted ones
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def strict_app(test_engine, test_sessionmaker, monkeypatch):
    """An app built with MCP_ALLOWED_HOSTS=testserver (strict mode)."""
    from plugtrack import db as db_module
    from plugtrack.main import create_app

    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")
    get_settings.cache_clear()
    monkeypatch.setattr(db_module, "engine", test_engine, raising=False)
    monkeypatch.setattr(db_module, "SessionLocal", test_sessionmaker, raising=False)

    application = create_app()

    async def _override_get_db():
        async with test_sessionmaker() as session:
            yield session

    application.dependency_overrides[db_module.get_db] = _override_get_db
    yield application
    application.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_strict_mode_rejects_disallowed_host_with_421(strict_app, test_sessionmaker):
    token = await _mint_token(test_sessionmaker)
    async with strict_app.router.lifespan_context(strict_app):
        transport = ASGITransport(app=strict_app)
        # nosec B113 — in-process ASGI transport, no network I/O to time out.
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:  # nosec B113
            headers = dict(_RPC_HEADERS)
            headers["Authorization"] = f"Bearer {token}"

            # Disallowed Host -> 421 Misdirected Request.
            headers["Host"] = "evil.example.com"
            r = await c.post(_MCP_URL, json=_init_payload(), headers=headers)
            assert r.status_code == 421, f"expected 421, got {r.status_code}: {r.text[:300]}"

            # Allowlisted Host -> served normally.
            headers["Host"] = "testserver"
            r = await c.post(_MCP_URL, json=_init_payload(), headers=headers)
            assert r.status_code < 400, f"allowlisted Host failed: {r.status_code} {r.text[:300]}"
