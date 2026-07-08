"""Session-cookie auth middleware.

Reads the `plugtrack_session` cookie, deserialises it via
`itsdangerous.URLSafeTimedSerializer(APP_SECRET_KEY, salt="session")`.
The cookie payload is `{"user_id": <int>}`. On non-exempt paths a
missing, tampered, or expired cookie returns 401. On success the
user_id is stored in `request.state.user_id` for downstream routes.

PLUG-L2: the timed serializer + `max_age=` in `loads` gives sessions a
server-side expiry — previously only the browser-side cookie max-age
applied, so a captured cookie stayed valid until the secret rotated.

Adding a path here weakens auth — requires explicit user sign-off.
"""

from __future__ import annotations

from collections.abc import Iterable

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SESSION_COOKIE_NAME = "plugtrack_session"
SESSION_SALT = "session"

# Adding a path here weakens auth — requires explicit user sign-off.
EXEMPT_PATHS: frozenset[str] = frozenset({"/api/health", "/api/setup", "/api/auth/login", "/mcp"})

# Paths in EXEMPT_PREFIX carry their own auth (e.g. the MCP bearer-token
# middleware) and must also bypass CSRF because they are not cookie-based.
# Matching is prefix: any request path that starts with one of these strings
# (or equals it exactly) is exempt. This is required because a mounted ASGI
# sub-app may receive sub-paths like /mcp/, /mcp/messages/ etc.
_EXEMPT_PREFIXES: tuple[str, ...] = ("/mcp",)


def make_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=SESSION_SALT)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates the signed session cookie on non-exempt paths."""

    def __init__(
        self,
        app,
        secret_key: str,
        cookie_name: str = SESSION_COOKIE_NAME,
        exempt_paths: Iterable[str] = EXEMPT_PATHS,
        max_age_seconds: int | None = None,
    ) -> None:
        super().__init__(app)
        self.cookie_name = cookie_name
        self.exempt_paths = frozenset(exempt_paths)
        self._serializer = make_serializer(secret_key)
        if max_age_seconds is None:
            from ..bootstrap import get_settings

            max_age_seconds = get_settings().session_max_age_seconds
        self._max_age_seconds = max_age_seconds

    def _read_user_id(self, request: Request) -> int | None:
        raw = request.cookies.get(self.cookie_name)
        if not raw:
            return None
        try:
            # BadTimeSignature (expired/tampered timestamp) subclasses
            # BadSignature, so one except covers both.
            payload = self._serializer.loads(raw, max_age=self._max_age_seconds)
        except BadSignature:
            return None
        if not isinstance(payload, dict):
            return None
        user_id = payload.get("user_id")
        if not isinstance(user_id, int):
            return None
        return user_id

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_exempt = path in self.exempt_paths or any(
            path == prefix or path.startswith(prefix + "/") for prefix in _EXEMPT_PREFIXES
        )

        user_id = self._read_user_id(request)
        if user_id is not None:
            request.state.user_id = user_id
        else:
            request.state.user_id = None

        if not is_exempt and user_id is None:
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )

        return await call_next(request)
