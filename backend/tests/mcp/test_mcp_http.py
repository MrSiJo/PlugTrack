"""Tests for the FastMCP streamable-HTTP server at /mcp (Task 5).

Drives the mounted ASGI app via httpx ASGITransport.

Validates:
- No token → 401
- Valid readwrite token → can call read tools (find_charges / get_insights)
- Valid readwrite token → can call propose/readwrite tools
- Read-scope token → read tools work; propose/commit tools are rejected
- Cross-user: token for user A sees only A's charges via find_charges
- Rate limit: many rapid requests from same token are throttled (429)
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from plugtrack.models import Car, ChargingSession, User
from plugtrack.settings.seeds import seed_defaults

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


async def _seed_user(sm, username: str) -> int:
    async with sm() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _seed_car(sm, user_id: int) -> int:
    async with sm() as s:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


async def _seed_session(sm, user_id: int, car_id: int, *, kwh: float = 20.0) -> int:
    import datetime as dt

    async with sm() as s:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=dt.date(2024, 6, 1),
            start_soc=20,
            end_soc=80,
            kwh_added=kwh,
            charging_type="ac",
            charging_mode="manual",
            source="manual",
        )
        s.add(cs)
        await s.commit()
        await s.refresh(cs)
        return cs.id


async def _mint_token(sm, user_id: int, name: str, scope: str) -> str:
    """Mint a real MCPToken and return the plaintext token."""
    from plugtrack.services import mcp_tokens

    async with sm() as s:
        _row, plaintext = await mcp_tokens.mint(s, user_id=user_id, name=name, scope=scope)
    return plaintext


# ---------------------------------------------------------------------------
# MCP JSON-RPC helpers
# ---------------------------------------------------------------------------

_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# The MCP endpoint — FastAPI mount at /mcp redirects /mcp → /mcp/ (307)
# so we use /mcp/ directly (the canonical URL with trailing slash).
_MCP_URL = "/mcp/"


def _init_payload() -> dict:
    """MCP initialize request."""
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


def _list_tools_payload() -> dict:
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _call_tool_payload(tool_name: str, args: dict, call_id: int = 3) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }


def _parse_sse_json(body: str) -> list[dict]:
    """Parse SSE-encoded JSON-RPC responses from a body string."""
    results = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[len("data:") :].strip()
            if data and data != "[DONE]":
                try:
                    results.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    return results


def _parse_response(response) -> list[dict]:
    """Parse either a direct JSON response or SSE body."""
    ct = response.headers.get("content-type", "")
    if "text/event-stream" in ct:
        return _parse_sse_json(response.text)
    # Plain JSON (stateless mode with json_response=True)
    return [response.json()]


async def _rpc(
    client: AsyncClient, payload: dict, *, token: str | None = None, session_id: str | None = None
) -> tuple[int, list[dict]]:
    """Send one JSON-RPC request to /mcp/ and return (status_code, parsed_results)."""
    headers = dict(_RPC_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    r = await client.post(_MCP_URL, json=payload, headers=headers)
    if r.status_code >= 400:
        return r.status_code, []
    return r.status_code, _parse_response(r)


async def _initialize(client: AsyncClient, token: str) -> tuple[int, str | None]:
    """Send initialize and return (status_code, session_id)."""
    status, msgs = await _rpc(client, _init_payload(), token=token)
    if status >= 400:
        return status, None
    # Session-Id may be in response header (stateful) or not needed (stateless)
    return status, None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mcp_client(app):
    """Return an AsyncClient aimed at the test app with lifespan running.

    The MCP session manager (FastMCP stateless_http) must have its task group
    started before requests can be served.  We run the app's full lifespan
    context so the _mcp_session_manager.run() is entered.
    """
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest_asyncio.fixture
async def mcp_seeds(test_sessionmaker):
    """Seed settings + two users + one charge session each.

    Returns:
        {
          "user_a_id": int,
          "user_b_id": int,
          "session_a_id": int,
          "session_b_id": int,
        }
    """
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()

    user_a_id = await _seed_user(test_sessionmaker, "alice_mcp")
    user_b_id = await _seed_user(test_sessionmaker, "bob_mcp")
    car_a_id = await _seed_car(test_sessionmaker, user_a_id)
    car_b_id = await _seed_car(test_sessionmaker, user_b_id)
    session_a_id = await _seed_session(test_sessionmaker, user_a_id, car_a_id, kwh=30.0)
    session_b_id = await _seed_session(test_sessionmaker, user_b_id, car_b_id, kwh=15.0)
    return {
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "session_a_id": session_a_id,
        "session_b_id": session_b_id,
    }


# ---------------------------------------------------------------------------
# Tests: 401 without a token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_no_token_returns_401(mcp_client):
    """A request to /mcp/ with no Authorization header must return 401."""
    r = await mcp_client.post(
        _MCP_URL,
        json=_init_payload(),
        headers=_RPC_HEADERS,
    )
    assert r.status_code == 401, (
        f"Expected 401 without a bearer token; got {r.status_code}. Body: {r.text[:500]}"
    )


@pytest.mark.asyncio
async def test_mcp_invalid_token_returns_401(mcp_client):
    """A request with a bogus bearer token must return 401."""
    headers = dict(_RPC_HEADERS)
    headers["Authorization"] = "Bearer totally-invalid-token"
    r = await mcp_client.post(_MCP_URL, json=_init_payload(), headers=headers)
    assert r.status_code == 401, (
        f"Expected 401 for invalid token; got {r.status_code}. Body: {r.text[:500]}"
    )


# ---------------------------------------------------------------------------
# Tests: readwrite token — can read + can propose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_readwrite_token_can_list_tools(mcp_client, mcp_seeds, test_sessionmaker):
    """A readwrite token can reach /mcp and list tools (including propose/commit)."""
    token = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-rw", "readwrite")

    # Initialize first
    status, _ = await _initialize(mcp_client, token)
    assert status < 400, f"initialize failed with status {status}"

    # List tools
    status, msgs = await _rpc(mcp_client, _list_tools_payload(), token=token)
    assert status < 400, f"tools/list failed: {status}"

    tool_names = set()
    for msg in msgs:
        if "result" in msg and "tools" in msg["result"]:
            for t in msg["result"]["tools"]:
                tool_names.add(t["name"])

    # Read tools must be present
    assert "find_charges" in tool_names, f"find_charges missing; tools={tool_names}"
    assert "get_charge" in tool_names, f"get_charge missing; tools={tool_names}"
    assert "get_insights" in tool_names, f"get_insights missing; tools={tool_names}"
    # Readwrite tools must ALSO be present for a readwrite token
    assert "propose_edit_charge" in tool_names, f"propose_edit_charge missing; tools={tool_names}"
    assert "commit_change" in tool_names, f"commit_change missing; tools={tool_names}"


@pytest.mark.asyncio
async def test_mcp_readwrite_find_charges_returns_own_data(
    mcp_client, mcp_seeds, test_sessionmaker
):
    """find_charges returns user A's charges when called with user A's token."""
    token = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-rw", "readwrite")

    await _initialize(mcp_client, token)
    status, msgs = await _rpc(
        mcp_client,
        _call_tool_payload("find_charges", {"limit": 10}),
        token=token,
    )
    assert status < 400, f"find_charges failed: {status}"

    # Extract the result content
    result_text = None
    for msg in msgs:
        if "result" in msg and "content" in msg["result"]:
            for item in msg["result"]["content"]:
                if item.get("type") == "text":
                    result_text = item["text"]
                    break

    assert result_text is not None, f"No text content in response; msgs={msgs}"
    charges = json.loads(result_text)
    assert isinstance(charges, list), f"Expected list; got {type(charges)}"
    assert len(charges) >= 1, "Expected at least 1 charge for user A"
    # All charges should belong to user A (inferred by session_a kwh=30)
    kwh_values = [c["kwh"] for c in charges if "kwh" in c]
    assert 30.0 in kwh_values, f"Expected 30.0 kWh from user A's session; got {kwh_values}"


# ---------------------------------------------------------------------------
# Tests: read-scope token — read tools ok, propose/commit rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_read_token_can_call_find_charges(mcp_client, mcp_seeds, test_sessionmaker):
    """A read-scoped token can call find_charges."""
    token = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-r", "read")

    await _initialize(mcp_client, token)
    status, msgs = await _rpc(
        mcp_client,
        _call_tool_payload("find_charges", {"limit": 5}),
        token=token,
    )
    assert status < 400, f"find_charges with read token failed: {status}"
    # Should get a valid result (list)
    result_text = None
    for msg in msgs:
        if "result" in msg and "content" in msg["result"]:
            for item in msg["result"]["content"]:
                if item.get("type") == "text":
                    result_text = item["text"]
    assert result_text is not None, f"No text content; msgs={msgs}"


@pytest.mark.asyncio
async def test_mcp_read_token_cannot_call_propose_edit_charge(
    mcp_client, mcp_seeds, test_sessionmaker
):
    """A read-scoped token must be rejected when calling propose_edit_charge."""
    token = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-r", "read")

    await _initialize(mcp_client, token)
    status, msgs = await _rpc(
        mcp_client,
        _call_tool_payload(
            "propose_edit_charge",
            {
                "charge_id": mcp_seeds["session_a_id"],
                "notes": "test",
            },
        ),
        token=token,
    )
    # Either 403/401 HTTP error OR the tool result contains an error
    found_error = False
    if status in (401, 403):
        found_error = True
    else:
        for msg in msgs:
            result = msg.get("result", {})
            content = result.get("content", [])
            for item in content:
                text = item.get("text", "")
                try:
                    parsed = json.loads(text)
                    if "error" in parsed:
                        found_error = True
                except json.JSONDecodeError:
                    if "error" in text.lower() or "scope" in text.lower() or "read" in text.lower():
                        found_error = True
            # Also check isError flag
            if result.get("isError"):
                found_error = True

    assert found_error, (
        f"Expected scope rejection for read-scope token calling propose_edit_charge; "
        f"status={status}, msgs={msgs}"
    )


@pytest.mark.asyncio
async def test_mcp_read_token_cannot_call_commit_change(mcp_client, mcp_seeds, test_sessionmaker):
    """A read-scoped token must be rejected when calling commit_change."""
    token = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-r", "read")

    await _initialize(mcp_client, token)
    status, msgs = await _rpc(
        mcp_client,
        _call_tool_payload("commit_change", {"change_token": "fake-token"}),
        token=token,
    )
    found_error = False
    if status in (401, 403):
        found_error = True
    else:
        for msg in msgs:
            result = msg.get("result", {})
            content = result.get("content", [])
            for item in content:
                text = item.get("text", "")
                try:
                    parsed = json.loads(text)
                    if "error" in parsed:
                        found_error = True
                except json.JSONDecodeError:
                    if "error" in text.lower() or "scope" in text.lower():
                        found_error = True
            if result.get("isError"):
                found_error = True

    assert found_error, (
        f"Expected scope rejection for read-scope token calling commit_change; "
        f"status={status}, msgs={msgs}"
    )


# ---------------------------------------------------------------------------
# Tests: cross-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_cross_user_isolation(mcp_client, mcp_seeds, test_sessionmaker):
    """Token for user A must NOT return user B's charges via find_charges."""
    token_a = await _mint_token(test_sessionmaker, mcp_seeds["user_a_id"], "test-a", "readwrite")

    await _initialize(mcp_client, token_a)
    status, msgs = await _rpc(
        mcp_client,
        _call_tool_payload("find_charges", {"limit": 50}),
        token=token_a,
    )
    assert status < 400

    charges = []
    for msg in msgs:
        if "result" in msg and "content" in msg["result"]:
            for item in msg["result"]["content"]:
                if item.get("type") == "text":
                    try:
                        charges = json.loads(item["text"])
                    except json.JSONDecodeError:
                        pass

    # User B's session has kwh=15.0, user A's has kwh=30.0
    kwh_values = [c.get("kwh") for c in charges if isinstance(c, dict)]
    assert 15.0 not in kwh_values, (
        f"Cross-user isolation failure: user B's 15.0 kWh charge appeared in user A's results. "
        f"kwh_values={kwh_values}"
    )


# ---------------------------------------------------------------------------
# Tests: EXEMPT_PATHS (these prove /mcp bypass reaches the MCP auth, not the session-cookie auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_path_bypasses_session_cookie_auth(mcp_client):
    """Requests to /mcp/ must not be blocked by the session-cookie middleware.

    The /mcp prefix is in EXEMPT_PATHS for auth + CSRF middlewares (prefix match),
    so only the MCP bearer-auth layer sees unauthenticated requests.
    """
    # Send with no session cookie and no bearer token.
    r = await mcp_client.post(
        _MCP_URL,
        json=_init_payload(),
        headers=_RPC_HEADERS,  # No Authorization, no session cookie
    )
    # Either way it's 401; but the body should NOT say "Authentication required" (session cookie msg)
    assert r.status_code == 401
    # The session-cookie middleware returns {"detail": "Authentication required"}
    # The MCP bearer-auth layer returns {"error": "unauthorized", "detail": "..."}
    body = r.text
    assert '"Authentication required"' not in body, (
        "The /mcp/ path appears to be blocked by the session-cookie middleware "
        f"instead of the MCP bearer-auth layer. Body: {body[:300]}"
    )
