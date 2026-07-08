"""Tests for GET /api/geocode (forward geocoding)."""

from __future__ import annotations

import pytest
from plugtrack.services.geocoding import GeocodeResult


class _StubProvider:
    def __init__(self, result):
        self._result = result

    async def forward(self, query):  # noqa: ARG002
        return self._result

    async def reverse(self, lat, lng):  # noqa: ARG002
        return None


@pytest.mark.asyncio
async def test_geocode_requires_auth(seeded_client):
    r = await seeded_client.get("/api/geocode?q=anywhere")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_geocode_returns_coords(authed_client, monkeypatch):
    import plugtrack.api.routes.geocode as mod

    result = GeocodeResult(
        address="Lysander Rd, Yeovil, BA20 2RP",
        provider="nominatim",
        lat=50.9512,
        lng=-2.6431,
    )
    monkeypatch.setattr(mod, "get_provider", lambda settings: _StubProvider(result))

    r = await authed_client.get("/api/geocode?q=Instavolt+McDonalds+Yeovil")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lat"] == 50.9512
    assert body["lng"] == -2.6431
    assert body["address"] == "Lysander Rd, Yeovil, BA20 2RP"
    assert body["provider"] == "nominatim"


@pytest.mark.asyncio
async def test_geocode_404_when_no_match(authed_client, monkeypatch):
    import plugtrack.api.routes.geocode as mod

    monkeypatch.setattr(mod, "get_provider", lambda settings: _StubProvider(None))

    r = await authed_client.get("/api/geocode?q=somewhere+unmatchable")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_geocode_requires_query(authed_client):
    r = await authed_client.get("/api/geocode")
    assert r.status_code == 422  # missing required q
