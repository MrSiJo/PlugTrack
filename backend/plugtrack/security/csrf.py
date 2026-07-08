"""Double-submit cookie CSRF middleware.

Pattern: a random 32-byte token is set in the `plugtrack_csrf` cookie on
every safe (GET/HEAD/OPTIONS) response. Mutating verbs
(POST/PUT/PATCH/DELETE) must echo that token back via the
`X-CSRF-Token` header. The middleware compares cookie vs header using
`secrets.compare_digest` (constant-time).

EXEMPT_PATHS bypasses the check entirely. Adding a path here weakens
CSRF — requires explicit user sign-off.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CSRF_COOKIE_NAME = "plugtrack_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Adding a path here weakens CSRF — requires explicit user sign-off.
# /mcp is exempt because it is a bearer-token–authenticated ASGI sub-app;
# it is non-cookie-based so the double-submit CSRF pattern does not apply.
EXEMPT_PATHS: frozenset[str] = frozenset({"/api/health", "/mcp"})

# Prefix-based exemptions for mounted sub-apps. Any path that starts with
# one of these strings (or equals it) bypasses CSRF checking. Required
# because the MCP streamable-HTTP transport uses sub-paths like /mcp/,
# /mcp/messages/ etc. (added 2026-06-19, user-authorised).
_CSRF_EXEMPT_PREFIXES: tuple[str, ...] = ("/mcp",)


def _generate_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


class CsrfMiddleware(BaseHTTPMiddleware):
    """Enforces double-submit CSRF on mutating requests."""

    def __init__(
        self,
        app,
        cookie_name: str = CSRF_COOKIE_NAME,
        header_name: str = CSRF_HEADER_NAME,
        exempt_paths: Iterable[str] = EXEMPT_PATHS,
        cookie_secure: bool = False,
    ) -> None:
        super().__init__(app)
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.exempt_paths = frozenset(exempt_paths)
        self.cookie_secure = cookie_secure

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path
        is_exempt = path in self.exempt_paths or any(
            path == prefix or path.startswith(prefix + "/") for prefix in _CSRF_EXEMPT_PREFIXES
        )

        if method not in SAFE_METHODS and not is_exempt:
            cookie_token = request.cookies.get(self.cookie_name)
            header_token = request.headers.get(self.header_name)
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
            ):
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"},
                    status_code=403,
                )

        response: Response = await call_next(request)

        # Issue/refresh the cookie on every safe response (including
        # exempt paths) so the SPA always has a token from the very
        # first request.
        if method in SAFE_METHODS:
            existing = request.cookies.get(self.cookie_name)
            token = existing or _generate_token()
            response.set_cookie(
                key=self.cookie_name,
                value=token,
                httponly=False,  # JS must read it to echo back as header
                samesite="lax",
                secure=self.cookie_secure,
                path="/",
            )

        return response
