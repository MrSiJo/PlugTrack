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

# UK postcode (e.g. "PL16 0AA", "TR15 3GF"); used as a geocode fallback because
# Nominatim often misses a full address but resolves the bare postcode.
_UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE)


def _extract_uk_postcode(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _UK_POSTCODE_RE.search(text)
    return m.group(1).upper() if m else None


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


async def clean_location_name(
    network: Optional[str], label: Optional[str], address: Optional[str],
    *, api_key: str, model: str, client=None,
) -> Optional[str]:
    """One-off LLM cleaner for backfill: returns a single '<Network> <Place>' line."""
    import httpx
    from .screenshot_extraction import RESPONSES_URL, extract_output_text
    prompt = (
        "Return ONLY a concise '<Network> <Place>' label for this EV charging location, "
        "e.g. 'Tesla Lifton', 'Osprey Land's End', 'MFG Morrisons Yeovil'. Normalise the "
        "network ('Supercharging' -> 'Tesla'); drop site noise ('Car Park', bay numbers, "
        "', UK'). No quotes, no other text."
    )
    user = f"network={network!r} label={label!r} address={address!r}"
    payload = {
        "model": model, "instructions": prompt,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user}]}],
        "reasoning": {"effort": "none"}, "max_output_tokens": 40,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.post(RESPONSES_URL, json=payload, headers=headers)
        if resp.status_code == 400 and "effort" in resp.text.lower():
            payload["reasoning"]["effort"] = "minimal"
            resp = await client.post(RESPONSES_URL, json=payload, headers=headers)
        resp.raise_for_status()
        text = extract_output_text(resp.json()).strip().strip('"')
        return text or None
    except Exception:
        logger.exception("clean_location_name failed")
        return None
    finally:
        if owns:
            await client.aclose()


async def backfill_import_session_locations(
    session: AsyncSession, *, user_id: int, provider: Optional[GeocodingProvider] = None,
    name_cleaner=None,
) -> int:
    """Link/create Locations for source='import' sessions that have none. Idempotent."""
    from ..models import ChargingSession
    rows = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.user_id == user_id,
                ChargingSession.source == "import",
                ChargingSession.location_id.is_(None),
            )
        )
    ).scalars().all()
    linked = 0
    for cs in rows:
        if not (cs.user_label or cs.notes):
            continue
        name = None
        if name_cleaner is not None:
            name = await name_cleaner(cs.charge_network, cs.user_label, cs.notes)
        if not name:
            name = compose_location_name(cs.charge_network, cs.user_label)
        loc_id = await resolve_ingested_location(
            session, user_id=user_id, place_name=name, raw_label=cs.user_label,
            address=cs.notes, network=cs.charge_network, provider=provider)
        if loc_id is not None:
            cs.location_id = loc_id
            linked += 1
    await session.flush()
    return linked


async def resolve_ingested_location(
    session: AsyncSession, *, user_id: int, place_name: Optional[str],
    raw_label: Optional[str], address: Optional[str], network: Optional[str],
    provider: Optional[GeocodingProvider] = None, radius_m: int = 250,
) -> Optional[int]:
    if provider is None:
        provider = get_provider(await _geocoding_settings(session))
    # Try the full address first, then a UK postcode pulled from it (Nominatim
    # often misses an address with ", United Kingdom," embedded but nails the
    # bare postcode), then the raw place label. First hit wins.
    candidates: list[str] = []
    if address and address.strip():
        candidates.append(address.strip())
    postcode = _extract_uk_postcode(address) or _extract_uk_postcode(raw_label)
    if postcode:
        candidates.append(postcode)
    if raw_label and raw_label.strip():
        candidates.append(raw_label.strip())
    result = None
    for query in dict.fromkeys(candidates):  # dedupe, preserve order
        result = await provider.forward(query)
        if result is not None:
            break
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
