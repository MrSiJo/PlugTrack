"""Tests for /api/health."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "commit" in body
