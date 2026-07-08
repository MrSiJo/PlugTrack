"""Reverse-geocoding provider abstraction.

Phase 5.1. The orchestrator schedules a fire-and-forget background task
on first creation of a `Location` row that calls into one of these
providers to populate `address`, `address_provider`, `address_fetched_at`.

Three real providers ship in v1:

- `NominatimProvider` — OpenStreetMap's free Nominatim service. Strict
  1 req/sec rate-limit per their ToS; we serialise + sleep via an
  `asyncio.Lock`. A descriptive `User-Agent` header is mandatory.
- `MapboxProvider` — paid; needs `geocoding_api_key`.
- `OpenCageProvider` — paid; needs `geocoding_api_key`.

Plus `NoOpProvider` for when `geocoding_enabled=false` (full-privacy
mode). The factory `get_provider(settings)` returns the right class
based on the catalogue values.

All providers are **async**; we use `httpx.AsyncClient` so the worker's
event loop is never blocked on network I/O. Failures return None — the
caller logs and leaves the address NULL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


_USER_AGENT = "plugtrack/2.0"
_NOMINATIM_RATE_LIMIT_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GeocodeResult:
    """Result of a successful reverse-geocode lookup.

    `lat` and `lng` echo the request — sanity-check for tests + so the
    caller can verify the provider didn't return a wildly different
    point. `provider` is the catalogue id (`nominatim` / `mapbox` /
    `opencage`).
    """

    address: str
    provider: str
    lat: float
    lng: float


@runtime_checkable
class GeocodingProvider(Protocol):
    """Reverse-geocode an (lat, lng) pair to a human-readable address."""

    async def reverse(self, lat: float, lng: float) -> GeocodeResult | None: ...

    async def forward(self, query: str) -> GeocodeResult | None: ...


class NoOpProvider:
    """Always returns None.

    Used when `geocoding_enabled=false` — the caller persists no address
    metadata. The location row is otherwise indistinguishable from one
    where geocoding succeeded but the provider returned no match.
    """

    name = "noop"

    async def reverse(self, lat: float, lng: float) -> GeocodeResult | None:  # noqa: ARG002
        return None

    async def forward(self, query: str) -> GeocodeResult | None:  # noqa: ARG002
        return None


class _RateLimiter:
    """Async-safe minimum-interval rate-limiter.

    Wraps `asyncio.Lock` + `time.monotonic()` to ensure consecutive
    `acquire()` calls are separated by at least `min_interval`. Tests
    inject a fake clock to avoid sleeping for real.
    """

    def __init__(
        self,
        min_interval: float,
        *,
        clock: callable | None = None,
        sleeper: callable | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._min_interval = min_interval
        self._last_at: float = 0.0
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep

    def _get_lock(self) -> asyncio.Lock:
        """Return the lock, rebuilding it if the running loop changed.

        The shared module-level limiter (PLUG-H3) outlives any single event
        loop; an asyncio.Lock binds to the loop that first awaits it, so under
        pytest (fresh loop per test) reusing the old lock would raise. The
        `_last_at` timestamp is monotonic-global, so rate limiting stays
        correct across the swap. Production has a single long-lived loop and
        never takes this branch.
        """
        loop = asyncio.get_running_loop()
        if self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def acquire(self) -> None:
        async with self._get_lock():
            now = self._clock()
            since = now - self._last_at
            if since < self._min_interval:
                await self._sleeper(self._min_interval - since)
            self._last_at = self._clock()


async def _get_response(
    url: str,
    *,
    params: dict,
    headers: dict | None = None,
    client: httpx.AsyncClient | None = None,
    log_label: str,
) -> httpx.Response | None:
    """GET with borrow-or-own client semantics; None on network error.

    Shared by all providers (PLUG-M6): borrows the injected client when
    present (tests), otherwise owns a short-lived one and closes it.
    Network/transport failures are logged and collapse to None — callers
    treat None exactly like a failed lookup.
    """
    try:
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
        try:
            return await client.get(url, params=params, headers=headers)
        finally:
            if owns_client:
                await client.aclose()
    except Exception:
        logger.exception("%s request failed", log_label)
        return None


# One limiter for the whole process: `get_provider` constructs a fresh
# NominatimProvider at several call sites, and per-instance limiters would
# let concurrent geocodes exceed Nominatim's 1 req/s ToS (PLUG-H3).
_SHARED_NOMINATIM_RATE_LIMITER = _RateLimiter(_NOMINATIM_RATE_LIMIT_SECONDS)


class NominatimProvider:
    """OpenStreetMap Nominatim reverse-geocoder.

    Free + key-less, but the Nominatim ToS demands:

    - A descriptive `User-Agent` header (we send `plugtrack/2.0`).
    - At most 1 request per second (we serialise via `_RateLimiter`).

    Failure (non-200, JSON missing `display_name`, network error) →
    return None and log.
    """

    name = "nominatim"
    BASE_URL = "https://nominatim.openstreetmap.org/reverse"
    SEARCH_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limiter: _RateLimiter | None = None,
    ) -> None:
        self._client = client
        # Default to the module-level shared limiter so every call site
        # (telegram ingest, MCP tools, geocode route, ingest_location)
        # collectively respects Nominatim's 1 req/s ToS (PLUG-H3).
        self._rate_limiter = rate_limiter or _SHARED_NOMINATIM_RATE_LIMITER

    async def reverse(self, lat: float, lng: float) -> GeocodeResult | None:
        await self._rate_limiter.acquire()
        params = {"format": "json", "lat": str(lat), "lon": str(lng)}
        headers = {"User-Agent": _USER_AGENT}
        response = await _get_response(
            self.BASE_URL,
            params=params,
            headers=headers,
            client=self._client,
            log_label="nominatim",
        )
        if response is None:
            return None

        if response.status_code != 200:
            logger.warning(
                "nominatim returned status %s for (%s, %s)",
                response.status_code,
                lat,
                lng,
            )
            return None

        try:
            payload = response.json()
        except Exception:
            logger.exception("nominatim returned non-JSON response")
            return None

        address = payload.get("display_name") if isinstance(payload, dict) else None
        if not address:
            return None
        return GeocodeResult(address=str(address), provider=self.name, lat=lat, lng=lng)

    async def forward(self, query: str) -> GeocodeResult | None:
        if not query or not query.strip():
            return None
        await self._rate_limiter.acquire()
        params = {"format": "json", "q": query, "limit": "1"}
        headers = {"User-Agent": _USER_AGENT}
        response = await _get_response(
            self.SEARCH_URL,
            params=params,
            headers=headers,
            client=self._client,
            log_label="nominatim search",
        )
        if response is None:
            return None
        if response.status_code != 200:
            logger.warning(
                "nominatim search returned status %s for %r", response.status_code, query
            )
            return None
        try:
            payload = response.json()
        except Exception:
            logger.exception("nominatim search returned non-JSON response")
            return None
        if not isinstance(payload, list) or not payload:
            return None
        top = payload[0]
        try:
            lat = float(top["lat"])
            lng = float(top["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        address = str(top.get("display_name") or query)
        return GeocodeResult(address=address, provider=self.name, lat=lat, lng=lng)


class MapboxProvider:
    """Mapbox reverse-geocoder. Requires `geocoding_api_key`."""

    name = "mapbox"
    BASE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("MapboxProvider requires geocoding_api_key")
        self._api_key = api_key
        self._client = client

    async def reverse(self, lat: float, lng: float) -> GeocodeResult | None:
        url = f"{self.BASE_URL}/{lng},{lat}.json"
        params = {"access_token": self._api_key}
        response = await _get_response(
            url,
            params=params,
            client=self._client,
            log_label="mapbox",
        )
        if response is None:
            return None

        if response.status_code != 200:
            logger.warning(
                "mapbox returned status %s for (%s, %s)",
                response.status_code,
                lat,
                lng,
            )
            return None

        try:
            payload = response.json()
        except Exception:
            logger.exception("mapbox returned non-JSON response")
            return None

        if not isinstance(payload, dict):
            return None
        features = payload.get("features") or []
        if not features or not isinstance(features, list):
            return None
        first = features[0]
        if not isinstance(first, dict):
            return None
        address = first.get("place_name")
        if not address:
            return None
        return GeocodeResult(address=str(address), provider=self.name, lat=lat, lng=lng)

    async def forward(self, query: str) -> GeocodeResult | None:
        if not query or not query.strip():
            return None
        url = f"{self.BASE_URL}/{quote(query)}.json"
        params = {"access_token": self._api_key, "limit": "1"}
        response = await _get_response(
            url,
            params=params,
            client=self._client,
            log_label="mapbox search",
        )
        if response is None:
            return None
        if response.status_code != 200:
            return None
        try:
            feats = (response.json() or {}).get("features") or []
        except Exception:
            return None
        if not feats:
            return None
        lng, lat = feats[0]["center"]
        return GeocodeResult(
            address=str(feats[0].get("place_name") or query),
            provider=self.name,
            lat=float(lat),
            lng=float(lng),
        )


class OpenCageProvider:
    """OpenCage reverse-geocoder. Requires `geocoding_api_key`."""

    name = "opencage"
    BASE_URL = "https://api.opencagedata.com/geocode/v1/json"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenCageProvider requires geocoding_api_key")
        self._api_key = api_key
        self._client = client

    async def reverse(self, lat: float, lng: float) -> GeocodeResult | None:
        params = {"q": f"{lat},{lng}", "key": self._api_key}
        response = await _get_response(
            self.BASE_URL,
            params=params,
            client=self._client,
            log_label="opencage",
        )
        if response is None:
            return None

        if response.status_code != 200:
            logger.warning(
                "opencage returned status %s for (%s, %s)",
                response.status_code,
                lat,
                lng,
            )
            return None

        try:
            payload = response.json()
        except Exception:
            logger.exception("opencage returned non-JSON response")
            return None

        if not isinstance(payload, dict):
            return None
        results = payload.get("results") or []
        if not results or not isinstance(results, list):
            return None
        first = results[0]
        if not isinstance(first, dict):
            return None
        address = first.get("formatted")
        if not address:
            return None
        return GeocodeResult(address=str(address), provider=self.name, lat=lat, lng=lng)

    async def forward(self, query: str) -> GeocodeResult | None:
        if not query or not query.strip():
            return None
        params = {"q": query, "key": self._api_key, "limit": "1"}
        response = await _get_response(
            self.BASE_URL,
            params=params,
            client=self._client,
            log_label="opencage search",
        )
        if response is None:
            return None
        if response.status_code != 200:
            return None
        try:
            results = (response.json() or {}).get("results") or []
        except Exception:
            return None
        if not results:
            return None
        try:
            geo = results[0]["geometry"]
            lat = float(geo["lat"])
            lng = float(geo["lng"])
        except (KeyError, TypeError, ValueError):
            return None
        return GeocodeResult(
            address=str(results[0].get("formatted") or query), provider=self.name, lat=lat, lng=lng
        )


def _bool_setting(raw, *, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    return bool(raw)


def get_provider(settings: dict) -> GeocodingProvider:
    """Factory: return the right provider based on settings.

    - `geocoding_enabled=false` → `NoOpProvider`.
    - `geocoding_provider=nominatim` (default) → `NominatimProvider`.
    - `geocoding_provider=mapbox` → `MapboxProvider` (requires
      `geocoding_api_key`; raises `ValueError` if missing).
    - `geocoding_provider=opencage` → `OpenCageProvider` (same).

    Unknown providers fall back to `NoOpProvider` with a logged warning.
    """
    enabled = _bool_setting(settings.get("geocoding_enabled"), default=True)
    if not enabled:
        return NoOpProvider()

    provider_name = (settings.get("geocoding_provider") or "nominatim").strip().lower()
    api_key = settings.get("geocoding_api_key") or ""

    if provider_name == "nominatim":
        return NominatimProvider()
    if provider_name == "mapbox":
        return MapboxProvider(api_key=api_key)
    if provider_name == "opencage":
        return OpenCageProvider(api_key=api_key)

    logger.warning(
        "unknown geocoding_provider %r — falling back to NoOpProvider",
        provider_name,
    )
    return NoOpProvider()


__all__ = [
    "GeocodeResult",
    "GeocodingProvider",
    "MapboxProvider",
    "NoOpProvider",
    "NominatimProvider",
    "OpenCageProvider",
    "get_provider",
]
