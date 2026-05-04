"""Security invariants — pinning tests with explicit sign-off semantics.

Failures here are *intentional* trip-wires: someone changed an exempt
path, removed CSRF from a mutating route, broke the one-shot setup
guarantee, or weakened the APP_SECRET_KEY validator. Update the pinned
constant ONLY after explicit user sign-off.

Wired into pre-commit as a manual-stage hook (see .pre-commit-config.yaml)
so it does not run on every commit but is trivial to invoke:

    pre-commit run --hook-stage manual security-invariants
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Route

from plugtrack.api.auth_middleware import EXEMPT_PATHS as AUTH_EXEMPT
from plugtrack.security.csrf import EXEMPT_PATHS as CSRF_EXEMPT
from tests.api.conftest import csrf_headers


# Pinned hash of the sorted union of EXEMPT_PATHS for both auth and CSRF
# middlewares. Recompute via:
#     python -c "import hashlib, json; \
#         print(hashlib.sha256(json.dumps({'auth': sorted([...]), \
#         'csrf': sorted([...])}, sort_keys=True).encode()).hexdigest())"
EXPECTED_EXEMPT_HASH = (
    "df16cd6b0d4a4df287c535c46da3ecdf24891a1891c6c795930cf07901357ff0"
)


def _compute_exempt_hash() -> str:
    payload = json.dumps(
        {"auth": sorted(AUTH_EXEMPT), "csrf": sorted(CSRF_EXEMPT)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_exempt_paths_have_not_changed():
    actual = _compute_exempt_hash()
    assert actual == EXPECTED_EXEMPT_HASH, (
        "An EXEMPT_PATHS set changed. Update this constant ONLY after "
        "explicit user sign-off.\n"
        f"  auth EXEMPT_PATHS: {sorted(AUTH_EXEMPT)}\n"
        f"  csrf EXEMPT_PATHS: {sorted(CSRF_EXEMPT)}\n"
        f"  expected hash: {EXPECTED_EXEMPT_HASH}\n"
        f"  actual hash:   {actual}"
    )


@pytest.mark.asyncio
async def test_csrf_fires_on_every_mutating_route_except_exempt(authed_client, app):
    """For every POST/PUT/PATCH/DELETE route in the app, sending it
    without an X-CSRF-Token header must yield 403 unless the path is
    explicitly listed in CSRF_EXEMPT_PATHS.
    """
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    failures: list[str] = []

    # Strip cookies so we go in unauthenticated for exempt paths but
    # keep the session cookie for non-exempt ones (we test CSRF, not
    # auth).
    for route in app.routes:
        if not isinstance(route, (APIRoute, Route)):
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path is None:
            continue
        for method in methods & mutating:
            r = await authed_client.request(method, path, json={})
            if path in CSRF_EXEMPT:
                # Exempt paths must NOT 403 on missing CSRF — they may
                # 4xx for other validation reasons but never 403 with a
                # CSRF detail.
                if r.status_code == 403 and "CSRF" in r.text:
                    failures.append(f"{method} {path} unexpectedly CSRF-blocked")
            else:
                if r.status_code != 403:
                    failures.append(
                        f"{method} {path} returned {r.status_code} without CSRF "
                        f"(expected 403)"
                    )

    assert not failures, "CSRF invariant violations:\n  " + "\n  ".join(failures)


@pytest.mark.asyncio
async def test_setup_is_one_shot(seeded_client):
    await seeded_client.get("/api/health")
    headers = csrf_headers(seeded_client)

    r1 = await seeded_client.post(
        "/api/setup",
        json={"username": "first", "password": "very-strong-pass"},
        headers=headers,
    )
    assert r1.status_code == 201, r1.text

    r2 = await seeded_client.post(
        "/api/setup",
        json={"username": "second", "password": "very-strong-pass"},
        headers=headers,
    )
    assert 400 <= r2.status_code < 500, (
        "second /api/setup must be a 4xx; got " f"{r2.status_code}"
    )


def test_settings_rejects_placeholder_app_secret(monkeypatch):
    monkeypatch.setenv(
        "APP_SECRET_KEY", "replace-with-output-of-bootstrap-script"
    )
    from plugtrack.bootstrap import Settings

    with pytest.raises(ValueError, match="placeholder"):
        Settings()


def test_settings_rejects_short_app_secret(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "short")
    from plugtrack.bootstrap import Settings

    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        Settings()
