"""Tests for the geocoding provider abstraction (Phase 5.1).

We mock httpx.AsyncClient.get per provider and assert the parsing +
factory behaviour. Nominatim's rate-limit is tested against a fake
clock + sleeper so the suite stays fast.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from plugtrack.services.geocoding import (
    GeocodeResult,
    MapboxProvider,
    NoOpProvider,
    NominatimProvider,
    OpenCageProvider,
    _RateLimiter,
    get_provider,
)


def _mock_response(status_code: int, json_body: Any) -> httpx.Response:
    request = httpx.Request("GET", "https://example.test/")
    return httpx.Response(
        status_code=status_code,
        json=json_body,
        request=request,
    )


# ---------------------------------------------------------------------------
# NoOp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_provider_always_returns_none():
    p = NoOpProvider()
    assert await p.reverse(50.0, -1.0) is None


# ---------------------------------------------------------------------------
# Nominatim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nominatim_parses_display_name():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(
        200, {"display_name": "10 Downing St, London"}
    )
    provider = NominatimProvider(client=client)
    result = await provider.reverse(51.5034, -0.1276)
    assert result == GeocodeResult(
        address="10 Downing St, London",
        provider="nominatim",
        lat=51.5034,
        lng=-0.1276,
    )

    args, kwargs = client.get.call_args
    assert args[0] == NominatimProvider.BASE_URL
    assert kwargs["headers"]["User-Agent"] == "plugtrack/2.0"
    assert kwargs["params"]["format"] == "json"
    assert kwargs["params"]["lat"] == "51.5034"
    assert kwargs["params"]["lon"] == "-0.1276"


@pytest.mark.asyncio
async def test_nominatim_returns_none_on_non_200():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(429, {"error": "rate limited"})
    provider = NominatimProvider(client=client)
    assert await provider.reverse(50.0, 0.0) is None


@pytest.mark.asyncio
async def test_nominatim_returns_none_when_no_display_name():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(200, {})
    provider = NominatimProvider(client=client)
    assert await provider.reverse(50.0, 0.0) is None


@pytest.mark.asyncio
async def test_nominatim_returns_none_on_network_error():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("boom")
    provider = NominatimProvider(client=client)
    assert await provider.reverse(50.0, 0.0) is None


@pytest.mark.asyncio
async def test_nominatim_rate_limiter_separates_calls():
    """Two consecutive calls should be ≥1 second apart per Nominatim ToS.

    We use a fake clock + sleeper so we can verify the sleeper was
    called with the right delta without actually waiting.
    """
    fake_now = [1000.0]
    sleeps: list[float] = []

    def fake_clock() -> float:
        return fake_now[0]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now[0] += seconds

    limiter = _RateLimiter(min_interval=1.0, clock=fake_clock, sleeper=fake_sleep)
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(200, {"display_name": "Somewhere"})
    provider = NominatimProvider(client=client, rate_limiter=limiter)

    await provider.reverse(50.0, 0.0)  # first call: no wait, last_at=1000
    # Simulate elapsed 0.2s before the second call.
    fake_now[0] += 0.2
    await provider.reverse(50.1, 0.0)  # should sleep for 0.8s

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# Mapbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mapbox_parses_first_feature_place_name():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(
        200,
        {
            "features": [
                {"place_name": "Tower of London, London, UK"},
                {"place_name": "should-not-pick-this"},
            ]
        },
    )
    provider = MapboxProvider(api_key="mb_key", client=client)
    result = await provider.reverse(51.508, -0.0759)
    assert result is not None
    assert result.address == "Tower of London, London, UK"
    assert result.provider == "mapbox"

    args, kwargs = client.get.call_args
    # URL ordering: lng,lat
    assert args[0].endswith("/-0.0759,51.508.json")
    assert kwargs["params"]["access_token"] == "mb_key"


def test_mapbox_requires_api_key():
    with pytest.raises(ValueError):
        MapboxProvider(api_key="")


@pytest.mark.asyncio
async def test_mapbox_returns_none_when_no_features():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(200, {"features": []})
    provider = MapboxProvider(api_key="mb_key", client=client)
    assert await provider.reverse(50.0, 0.0) is None


# ---------------------------------------------------------------------------
# OpenCage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencage_parses_first_result_formatted():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(
        200,
        {
            "results": [
                {"formatted": "Eiffel Tower, Paris, France"},
                {"formatted": "should-not-pick-this"},
            ]
        },
    )
    provider = OpenCageProvider(api_key="oc_key", client=client)
    result = await provider.reverse(48.8584, 2.2945)
    assert result is not None
    assert result.address == "Eiffel Tower, Paris, France"
    assert result.provider == "opencage"

    args, kwargs = client.get.call_args
    assert args[0] == OpenCageProvider.BASE_URL
    assert kwargs["params"]["q"] == "48.8584,2.2945"
    assert kwargs["params"]["key"] == "oc_key"


def test_opencage_requires_api_key():
    with pytest.raises(ValueError):
        OpenCageProvider(api_key="")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_noop_when_disabled():
    provider = get_provider({"geocoding_enabled": "false"})
    assert isinstance(provider, NoOpProvider)


def test_factory_returns_nominatim_default():
    provider = get_provider({"geocoding_enabled": "true"})
    assert isinstance(provider, NominatimProvider)


def test_factory_returns_nominatim_explicit():
    provider = get_provider(
        {"geocoding_enabled": "true", "geocoding_provider": "nominatim"}
    )
    assert isinstance(provider, NominatimProvider)


def test_factory_returns_mapbox_with_key():
    provider = get_provider(
        {
            "geocoding_enabled": "true",
            "geocoding_provider": "mapbox",
            "geocoding_api_key": "mb_key",
        }
    )
    assert isinstance(provider, MapboxProvider)


def test_factory_raises_when_mapbox_missing_key():
    with pytest.raises(ValueError):
        get_provider(
            {
                "geocoding_enabled": "true",
                "geocoding_provider": "mapbox",
                "geocoding_api_key": "",
            }
        )


def test_factory_raises_when_opencage_missing_key():
    with pytest.raises(ValueError):
        get_provider(
            {
                "geocoding_enabled": "true",
                "geocoding_provider": "opencage",
            }
        )


def test_factory_unknown_provider_falls_back_to_noop():
    provider = get_provider(
        {"geocoding_enabled": "true", "geocoding_provider": "garmin-or-something"}
    )
    assert isinstance(provider, NoOpProvider)


# ---------------------------------------------------------------------------
# Forward geocoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nominatim_forward_parses_first_hit():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(
        200, [{"lat": "50.6437", "lon": "-4.2846", "display_name": "Lifton, PL16 0AA"}]
    )
    provider = NominatimProvider(client=client)
    result = await provider.forward("1 Fore Street, Lifton, PL16 0AA")
    assert result == GeocodeResult(address="Lifton, PL16 0AA", provider="nominatim",
                                   lat=50.6437, lng=-4.2846)
    args, kwargs = client.get.call_args
    assert args[0] == NominatimProvider.SEARCH_URL
    assert kwargs["params"]["q"] == "1 Fore Street, Lifton, PL16 0AA"
    assert kwargs["headers"]["User-Agent"] == "plugtrack/2.0"


@pytest.mark.asyncio
async def test_nominatim_forward_empty_list_returns_none():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(200, [])
    assert await NominatimProvider(client=client).forward("nowhere") is None


@pytest.mark.asyncio
async def test_nominatim_forward_blank_query_returns_none():
    assert await NominatimProvider().forward("  ") is None


@pytest.mark.asyncio
async def test_noop_forward_returns_none():
    assert await NoOpProvider().forward("anywhere") is None
