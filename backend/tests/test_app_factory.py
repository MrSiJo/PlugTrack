"""Tests for the FastAPI app factory + lifespan."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from plugtrack.models import Setting
from plugtrack.settings.catalogue import CATALOGUE


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "commit" in body


@pytest.mark.asyncio
async def test_lifespan_seeds_catalogue(app, test_sessionmaker):
    # ASGITransport does not drive lifespan events automatically; invoke
    # the FastAPI lifespan context directly to exercise the seeder.
    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            result = await session.execute(select(func.count()).select_from(Setting))
            count = result.scalar_one()
    assert count == len(CATALOGUE)


def test_multi_worker_tripwire_raises(monkeypatch):
    from plugtrack.main import _assert_single_worker

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError, match="WEB_CONCURRENCY=1"):
        _assert_single_worker()


def test_single_worker_allowed(monkeypatch):
    from plugtrack.main import _assert_single_worker

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    _assert_single_worker()  # no raise

    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    _assert_single_worker()  # no raise


@pytest.mark.asyncio
async def test_app_includes_health_route(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/health" in paths
    # Sanity: WEB_CONCURRENCY is not poisoned by another test.
    assert os.getenv("WEB_CONCURRENCY") in (None, "1")
