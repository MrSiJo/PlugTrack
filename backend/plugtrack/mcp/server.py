"""FastMCP streamable-HTTP server for PlugTrack.

Mounts at /mcp (registered in create_app()). Uses a custom ASGI bearer-token
auth middleware that wraps the FastMCP ASGI app — cleaner than the SDK's
OAuth-only built-in auth which requires issuer/resource-server URLs and an
OAuth infrastructure we don't have.

Auth flow
---------
1. The ASGI auth wrapper reads ``Authorization: Bearer <token>``.
2. Calls ``mcp_tokens.verify(session, token)`` — looks up the hash, returns
   the MCPToken row (with user_id + scope) or None.
3. On success, stores user_id + scope in contextvars so tool handlers can
   read them via ``get_mcp_context()``.
4. On failure (missing/invalid token), returns HTTP 401.

Scopes
------
- ``read``     — find_charges, get_charge, get_insights only.
- ``readwrite``— all of the above + propose_* + commit_change.

Rate limiting
-------------
A simple in-memory sliding-window counter (per bearer token hash) caps
requests at 60/minute per identity. Returns HTTP 429 on excess.

Contextvars
-----------
``_user_id_var`` and ``_scope_var`` are ContextVar objects set per-request by
the auth middleware and read by tool handlers via ``get_mcp_context()``.

Lifespan wiring
---------------
FastMCP stateless_http mode still requires the session_manager task group to
be running.  ``build_mcp_app(db_sessionmaker)`` returns
``(wrapped_asgi_app, session_manager)``; the caller (``create_app()`` in
``main.py``) must enter ``session_manager.run()`` inside the app's lifespan.
The module exposes ``_mcp_session_manager`` so the main lifespan can reach it.

NOTE: do NOT use ``from __future__ import annotations`` in this file — the
FastMCP SDK uses ``inspect.signature()`` at tool-registration time and cannot
handle stringified annotations (PEP 563).  Use concrete types directly.
"""

import collections
import contextvars
import json
import logging
import time
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-request context (set by auth middleware, read by tools)
# ---------------------------------------------------------------------------

_user_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mcp_user_id", default=None
)
_scope_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_scope", default=None)


def get_mcp_context() -> tuple[int, str]:
    """Return ``(user_id, scope)`` for the current MCP request.

    Raises RuntimeError if called outside an authenticated MCP request.
    """
    user_id = _user_id_var.get()
    scope = _scope_var.get()
    if user_id is None or scope is None:
        raise RuntimeError("get_mcp_context() called outside an authenticated MCP request")
    return user_id, scope


# ---------------------------------------------------------------------------
# Rate limiter (sliding-window per identity)
# ---------------------------------------------------------------------------

_RATE_LIMIT_REQUESTS = 60  # requests per window
_RATE_LIMIT_WINDOW = 60.0  # seconds


class _RateLimiter:
    """Simple sliding-window counter per identity string."""

    def __init__(self, limit: int = _RATE_LIMIT_REQUESTS, window: float = _RATE_LIMIT_WINDOW):
        self._limit = limit
        self._window = window
        # identity -> deque of request timestamps
        self._windows: dict = {}

    def is_allowed(self, identity: str) -> bool:
        now = time.monotonic()
        dq = self._windows.setdefault(identity, collections.deque())
        # Evict entries older than the window
        while dq and dq[0] < now - self._window:
            dq.popleft()
        if len(dq) >= self._limit:
            return False
        dq.append(now)
        return True


_rate_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# ASGI bearer-token auth + rate-limit middleware
# ---------------------------------------------------------------------------


class _McpAuthMiddleware:
    """Wraps the FastMCP ASGI app with bearer-token auth and rate limiting.

    For ``http`` scope (Streamable HTTP transport):
      1. Extract ``Authorization: Bearer <token>`` from headers.
      2. Verify via ``mcp_tokens.verify``.
      3. Rate-limit per token (hash of first 16 chars).
      4. Inject user_id + scope into contextvars.
      5. Call the inner app.

    For ``lifespan`` scope: pass through (the inner Starlette app's lifespan
    handles session manager startup/shutdown).
    """

    def __init__(self, app: ASGIApp, db_sessionmaker: Any) -> None:
        self._app = app
        self._db = db_sessionmaker

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass lifespan through so the inner Starlette app's lifespan runs
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Extract Bearer token from headers
        headers: dict = {}
        for k, v in scope.get("headers", []):
            headers[k.lower()] = v
        auth_bytes = headers.get(b"authorization", b"")
        auth_header = auth_bytes.decode("utf-8", errors="replace")

        token_str: str | None = None
        if auth_header.startswith("Bearer "):
            token_str = auth_header[len("Bearer ") :]

        if not token_str:
            await _send_401(scope, receive, send, "Bearer token required")
            return

        # Verify the token against the DB
        from ..services import mcp_tokens as _mcp_tokens

        user_id: int | None = None
        scope_str: str | None = None

        try:
            async with self._db() as session:
                row = await _mcp_tokens.verify(session, token_str)
                if row is not None:
                    user_id = row.user_id
                    scope_str = row.scope
        except Exception:
            _log.exception("MCP token verification failed (DB error)")
            await _send_401(scope, receive, send, "Token verification failed")
            return

        if user_id is None:
            await _send_401(scope, receive, send, "Invalid or revoked bearer token")
            return

        # Rate limit by short hash of the token (avoids storing plaintext)
        import hashlib

        identity = hashlib.sha256(token_str.encode()).hexdigest()[:16]
        if not _rate_limiter.is_allowed(identity):
            await _send_429(scope, receive, send)
            return

        # Inject context vars, then call inner app
        uid_token = _user_id_var.set(user_id)
        scope_token = _scope_var.set(scope_str)
        try:
            await self._app(scope, receive, send)
        finally:
            _user_id_var.reset(uid_token)
            _scope_var.reset(scope_token)


async def _send_json_response(
    scope: Scope, receive: Receive, send: Send, status: int, body: dict
) -> None:
    body_bytes = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body_bytes})


async def _send_401(scope: Scope, receive: Receive, send: Send, detail: str) -> None:
    await _send_json_response(
        scope,
        receive,
        send,
        401,
        {
            "detail": detail,
            "error": "unauthorized",
        },
    )


async def _send_429(scope: Scope, receive: Receive, send: Send) -> None:
    await _send_json_response(
        scope,
        receive,
        send,
        429,
        {
            "detail": "Rate limit exceeded. Please wait before retrying.",
            "error": "rate_limited",
        },
    )


# ---------------------------------------------------------------------------
# Scope enforcement helpers (called inside tool handlers)
# ---------------------------------------------------------------------------


def require_readwrite() -> dict | None:
    """Return a scope-error dict if the current token is read-only, else None."""
    _, current_scope = get_mcp_context()
    if current_scope != "readwrite":
        return {"error": "readwrite scope required for this tool"}
    return None


# ---------------------------------------------------------------------------
# FastMCP server + tool definitions
# ---------------------------------------------------------------------------

# Module-level reference to the session manager so create_app()'s lifespan
# can start/stop it.  Set by build_mcp_app(); None until called.
_mcp_session_manager = None


def build_mcp_app(db_sessionmaker: Any) -> ASGIApp:
    """Build the FastMCP app, register tools, and return the wrapped ASGI app.

    Also stores the session_manager in module-level ``_mcp_session_manager``
    so the caller can wire it into the FastAPI lifespan.

    Called once from ``create_app()`` at startup; the result is mounted
    at ``/mcp``.

    IMPORTANT: ``from __future__ import annotations`` must NOT be active when
    this function runs (or in this module) — the FastMCP SDK inspects tool
    function signatures using ``inspect.signature()`` and cannot handle PEP 563
    stringified annotations.
    """
    global _mcp_session_manager

    from mcp.server.fastmcp import FastMCP

    from ..mcp import tools as _tools

    # streamable_http_path="/" makes the Starlette route at "/" so that when
    # FastAPI mounts this ASGI app at /mcp the effective URL is exactly /mcp
    # (not /mcp/mcp which would be the default /mcp path within the sub-app).
    mcp = FastMCP(
        "PlugTrack",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -------------------------------------------------------------------
    # READ tools — available to all scopes (read + readwrite)
    # -------------------------------------------------------------------

    @mcp.tool()
    async def find_charges(
        limit: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        location_id: int | None = None,
    ) -> str:
        """Find recent charging sessions (most-recent first).

        Args:
            limit: Maximum number of results (default 10).
            date_from: ISO date string (YYYY-MM-DD) inclusive lower bound.
            date_to: ISO date string (YYYY-MM-DD) inclusive upper bound.
            location_id: Filter to a specific location id.

        Returns:
            JSON array of charge dicts.
        """
        import datetime as dt

        user_id, _ = get_mcp_context()
        df = dt.date.fromisoformat(date_from) if date_from else None
        dt2 = dt.date.fromisoformat(date_to) if date_to else None
        async with db_sessionmaker() as session:
            result = await _tools.find_charges(
                session,
                user_id,
                date_from=df,
                date_to=dt2,
                location_id=location_id,
                limit=limit,
            )
        return json.dumps(result, default=str)

    @mcp.tool()
    async def get_charge(charge_id: int) -> str:
        """Get a single charging session by ID.

        Args:
            charge_id: The numeric ID of the charge session.

        Returns:
            JSON dict of the charge, or null if not found / not owned.
        """
        user_id, _ = get_mcp_context()
        async with db_sessionmaker() as session:
            result = await _tools.get_charge(session, user_id, charge_id)
        return json.dumps(result, default=str)

    @mcp.tool()
    async def get_insights(
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        """Get charging insights / stats for a date window.

        Args:
            date_from: ISO date string (YYYY-MM-DD) inclusive lower bound.
            date_to: ISO date string (YYYY-MM-DD) inclusive upper bound.

        Returns:
            JSON dict with totals, home/public split, network breakdown,
            and spend/energy over time.
        """
        import datetime as dt

        user_id, _ = get_mcp_context()
        df = dt.date.fromisoformat(date_from) if date_from else None
        dt2 = dt.date.fromisoformat(date_to) if date_to else None
        async with db_sessionmaker() as session:
            result = await _tools.get_insights(session, user_id, date_from=df, date_to=dt2)
        return json.dumps(result, default=str)

    # -------------------------------------------------------------------
    # READWRITE tools — rejected for read-scoped tokens
    # -------------------------------------------------------------------

    @mcp.tool()
    async def propose_create_location(
        name: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        address: str | None = None,
    ) -> str:
        """Propose creating a new location (two-phase: no DB write yet).

        Requires readwrite scope.

        Args:
            name: Human-readable label for the location.
            lat: Latitude (WGS84). Either (lat, lng) or address required.
            lng: Longitude (WGS84).
            address: Street address to geocode (used when lat/lng not provided).

        Returns:
            JSON with summary and change_token on success, or error dict.
        """
        err = require_readwrite()
        if err is not None:
            return json.dumps(err)
        user_id, _ = get_mcp_context()
        async with db_sessionmaker() as session:
            result = await _tools.propose_create_location(
                session, user_id, name=name, lat=lat, lng=lng, address=address
            )
        return json.dumps(result, default=str)

    @mcp.tool()
    async def propose_set_location(
        charge_id: int,
        location_id: int | None = None,
        location_name: str | None = None,
    ) -> str:
        """Propose assigning a location to a charge session (two-phase).

        Requires readwrite scope.

        Args:
            charge_id: The numeric ID of the charge session.
            location_id: Numeric location ID (preferred).
            location_name: Name of an existing location (alternative).

        Returns:
            JSON with summary and change_token on success, or error dict.
        """
        err = require_readwrite()
        if err is not None:
            return json.dumps(err)
        user_id, _ = get_mcp_context()
        async with db_sessionmaker() as session:
            result = await _tools.propose_set_location(
                session,
                user_id,
                charge_id=charge_id,
                location_id=location_id,
                location_name=location_name,
            )
        return json.dumps(result, default=str)

    @mcp.tool()
    async def propose_edit_charge(
        charge_id: int,
        kwh: float | None = None,
        price_p_per_kwh: float | None = None,
        total_cost_p: int | None = None,
        start_soc: int | None = None,
        end_soc: int | None = None,
        date: str | None = None,
        network: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Propose editing fields on a charge session (two-phase).

        Requires readwrite scope. Does NOT write to DB — call commit_change
        with the returned change_token to apply.

        Args:
            charge_id: The numeric ID of the charge session.
            kwh: New energy added (kWh).
            price_p_per_kwh: Override rate (pence per kWh).
            total_cost_p: Override total cost (pence).
            start_soc: State-of-charge at charge start (%).
            end_soc: State-of-charge at charge end (%).
            date: New date (ISO YYYY-MM-DD).
            network: Charge network name.
            notes: Free-text notes.

        Returns:
            JSON with summary and change_token on success, or error dict.
        """
        err = require_readwrite()
        if err is not None:
            return json.dumps(err)
        import datetime as dt

        user_id, _ = get_mcp_context()
        date_obj = dt.date.fromisoformat(date) if date else None
        async with db_sessionmaker() as session:
            result = await _tools.propose_edit_charge(
                session,
                user_id,
                charge_id=charge_id,
                kwh=kwh,
                price_p_per_kwh=price_p_per_kwh,
                total_cost_p=total_cost_p,
                start_soc=start_soc,
                end_soc=end_soc,
                date=date_obj,
                network=network,
                notes=notes,
            )
        return json.dumps(result, default=str)

    @mcp.tool()
    async def commit_change(change_token: str) -> str:
        """Apply a pending two-phase change.

        Requires readwrite scope.

        Args:
            change_token: The token returned by a propose_* call.

        Returns:
            JSON with ok=true and details on success, or error dict on failure.
        """
        err = require_readwrite()
        if err is not None:
            return json.dumps(err)
        user_id, _ = get_mcp_context()
        async with db_sessionmaker() as session:
            result = await _tools.commit_change(session, user_id, change_token)
        return json.dumps(result, default=str)

    # Build the Starlette ASGI app (also initialises the session_manager)
    raw_starlette_app = mcp.streamable_http_app()

    # Store the session manager for lifespan wiring in create_app()
    _mcp_session_manager = mcp.session_manager

    # Wrap with auth + rate-limit middleware
    return _McpAuthMiddleware(raw_starlette_app, db_sessionmaker)
