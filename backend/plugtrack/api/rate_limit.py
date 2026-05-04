"""Slowapi rate limiter — singleton wired into the FastAPI app.

The limiter is keyed by the remote IP address. `headers_enabled=True`
makes slowapi emit the standard `X-RateLimit-*` and `Retry-After`
headers on rate-limited responses.

To activate this on the app, set `app.state.limiter = limiter` and
register `slowapi._rate_limit_exceeded_handler` for `RateLimitExceeded`.
Routes opt in via `@limiter.limit("N/period")`.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
