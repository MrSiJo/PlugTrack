"""Slowapi rate limiter — singleton wired into the FastAPI app.

The limiter is keyed by the *real* client IP. `headers_enabled=True`
makes slowapi emit the standard `X-RateLimit-*` and `Retry-After`
headers on rate-limited responses.

In the shipped topology the API sits behind an nginx container, so the
immediate TCP peer (`request.client.host`) is the proxy's IP for *every*
user — keying on it alone would make a per-route limit a single global
bucket. `client_ip_key` therefore honours the left-most `X-Forwarded-For`
entry, but ONLY when the immediate peer is a private/loopback address (i.e.
the trusted reverse proxy). A direct hit on the published port from a public
peer cannot spoof its identity via a forged `X-Forwarded-For` header.

To activate this on the app, set `app.state.limiter = limiter` and
register `slowapi._rate_limit_exceeded_handler` for `RateLimitExceeded`.
Routes opt in via `@limiter.limit("N/period")`.
"""
from __future__ import annotations

import ipaddress

from slowapi import Limiter
from starlette.requests import Request


def _is_trusted_proxy(ip: str) -> bool:
    """True when *ip* is a private/loopback address (a local reverse proxy)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def client_ip_key(request: Request) -> str:
    """Rate-limit key: the real client IP, proxy-aware and spoof-resistant."""
    peer = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(peer):
        client = forwarded.split(",", 1)[0].strip()
        if client:
            return client
    return peer


limiter = Limiter(key_func=client_ip_key, headers_enabled=True)
