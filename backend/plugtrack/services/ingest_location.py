# backend/plugtrack/services/ingest_location.py
"""Turn an ingested charge's place name/address into a real Location.

Forward-geocodes the address (falling back to the raw label) to coordinates,
then reuses the GPS proximity clustering (`find_or_create_location`) to link an
existing nearby Location or create a new named one. Used at commit time only —
never during the confirm-card preview. A geocoding failure returns None and the
caller leaves the charge text-only.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Setting
from .geocoding import GeocodingProvider, get_provider
from .location_clustering import find_or_create_location

logger = logging.getLogger(__name__)

_FILLER = {"nt", "car", "park", "the", "uk"}


def _normalise_network(network: Optional[str]) -> Optional[str]:
    if not network:
        return None
    n = network.strip()
    low = n.lower()
    if "supercharg" in low:          # "Supercharging" / "Tesla Supercharging"
        return "Tesla"
    # strip a trailing "Charging" word: "RAW Charging" -> "RAW"
    n = re.sub(r"\s+charging$", "", n, flags=re.IGNORECASE).strip()
    return n or None


def _short_place(label: Optional[str], net: Optional[str]) -> Optional[str]:
    if not label:
        return None
    seg = label.split(",")[0].strip()           # first comma segment
    net_words = {w.lower() for w in (net or "").split()}
    out: list[str] = []
    for tok in seg.split():
        low = tok.lower()
        if low in net_words or low in _FILLER or tok.isdigit():
            continue
        out.append(tok.upper().title() if tok.isupper() and len(tok) > 3 else tok)
    return " ".join(out) or None


def compose_location_name(network: Optional[str], label: Optional[str]) -> Optional[str]:
    """Deterministic '<Network> <Place>' fallback when no LLM short name exists."""
    net = _normalise_network(network)
    place = _short_place(label, net)
    parts = [p for p in (net, place) if p]
    return " ".join(parts) or None


async def _geocoding_settings(session: AsyncSession) -> dict:
    keys = ["geocoding_enabled", "geocoding_provider", "geocoding_api_key"]
    rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    return {r.key: r.value for r in rows}


async def resolve_ingested_location(
    session: AsyncSession, *, user_id: int, place_name: Optional[str],
    raw_label: Optional[str], address: Optional[str], network: Optional[str],
    provider: Optional[GeocodingProvider] = None, radius_m: int = 250,
) -> Optional[int]:
    if provider is None:
        provider = get_provider(await _geocoding_settings(session))
    query = (address or raw_label or "").strip()
    if not query:
        return None
    result = await provider.forward(query)
    if result is None:
        return None
    loc, created = await find_or_create_location(
        session, user_id, result.lat, result.lng, radius_m=radius_m
    )
    if created:
        loc.name = place_name
        loc.default_charge_network = network
        loc.address = address
    else:
        if not loc.name and place_name:
            loc.name = place_name
        if not loc.default_charge_network and network:
            loc.default_charge_network = network
        if not loc.address and address:
            loc.address = address
    loc.visit_count = (loc.visit_count or 0) + 1
    loc.last_visited_at = datetime.now(timezone.utc)
    await session.flush()
    return loc.id
