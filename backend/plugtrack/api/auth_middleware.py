"""Session-cookie auth middleware.

Reads the `plugtrack_session` cookie, deserialises it via
`itsdangerous.URLSafeSerializer(APP_SECRET_KEY, salt="session")`. The
cookie payload is `{"user_id": <int>}`. On non-exempt paths a missing
or tampered cookie returns 401. On success the user_id is stored in
`request.state.user_id` for downstream routes.

Adding a path here weakens auth — requires explicit user sign-off.
"""
from __future__ import annotations

from typing import Iterable, Optional

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


SESSION_COOKIE_NAME = "plugtrack_session"
SESSION_SALT = "session"

# Adding a path here weakens auth — requires explicit user sign-off.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {"/api/health", "/api/setup", "/api/auth/login"}
)


def make_serializer(secret_key: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret_key, salt=SESSION_SALT)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates the signed session cookie on non-exempt paths."""

    def __init__(
        self,
        app,
        secret_key: str,
        cookie_name: str = SESSION_COOKIE_NAME,
        exempt_paths: Iterable[str] = EXEMPT_PATHS,
    ) -> None:
        super().__init__(app)
        self.cookie_name = cookie_name
        self.exempt_paths = frozenset(exempt_paths)
        self._serializer = make_serializer(secret_key)

    def _read_user_id(self, request: Request) -> Optional[int]:
        raw = request.cookies.get(self.cookie_name)
        if not raw:
            return None
        try:
            payload = self._serializer.loads(raw)
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
        is_exempt = path in self.exempt_paths

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
