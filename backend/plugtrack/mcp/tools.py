"""MCP tool core — user-scoped read + two-phase propose/commit create/update.

All functions are async, all filter by caller's user_id.
Returns plain dicts (JSON-serialisable); on error returns {"error": "..."} —
never raises raw exceptions to the caller.

Two-phase mutation design
--------------------------
propose_*    → validate ownership, build a human-readable summary, store the
               pending change in the in-memory _CHANGE_STORE under a fresh
               change_token, return {summary, change_token} WITHOUT writing DB.

commit_change → look up the token; reject if missing / expired / already-used /
               stored user_id != caller; apply via service helpers; mark as used.

Change-token store (_CHANGE_STORE)
------------------------------------
In-memory dict, process-local (intentional — spec states single-worker assumption;
tokens degrade gracefully on restart).

  key  : change_token (secrets.token_urlsafe(12))
  value: {
      "user_id": int,
      "created_at": datetime (UTC),
      "used": bool,
      "kind": str,
      "data": dict,   # change-specific payload
  }

TTL is _TOKEN_TTL_SECONDS (10 min). commit_change checks expiry before applying.
"""
from __future__ import annotations

import datetime as dt
import secrets
from datetime import timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession, Location, Setting
from ..services import insights_stats
from ..services.cost_apply import apply_cost
from ..services.geocoding import get_provider
from ..services.location_clustering import find_or_create_location


# ---------------------------------------------------------------------------
# Money formatting (display convention for the conversational layer)
#   - totals / spend / per-charge cost → pounds, "£X.XX"
#   - per-kWh rates / unit prices       → pence,  "N.Np/kWh"
# Tool outputs carry pre-formatted strings so the agent restates them verbatim
# (grounding discipline) instead of converting pence itself.
# ---------------------------------------------------------------------------

_KM_PER_MI = 1.609344


def _format_gbp(pence) -> Optional[str]:
    if pence is None:
        return None
    return f"£{pence / 100:.2f}"


def _format_rate(p) -> Optional[str]:
    if p is None:
        return None
    return f"{p:.1f}p/kWh"


def _annotate_money(obj):
    """Recursively add display-formatted money fields to a tool-result structure.

    For any dict carrying `spend_pence` add a pounds string `spend`; for any
    dict carrying `avg_p_per_kwh` add a pence-rate string `avg_price`.
    """
    if isinstance(obj, dict):
        if isinstance(obj.get("spend_pence"), (int, float)):
            obj["spend"] = _format_gbp(obj["spend_pence"])
        if isinstance(obj.get("avg_p_per_kwh"), (int, float)):
            obj["avg_price"] = _format_rate(obj["avg_p_per_kwh"])
        for v in obj.values():
            _annotate_money(v)
    elif isinstance(obj, list):
        for v in obj:
            _annotate_money(v)
    return obj


# ---------------------------------------------------------------------------
# Change-token store
# ---------------------------------------------------------------------------

_CHANGE_STORE: dict[str, dict] = {}
_TOKEN_TTL_SECONDS = 600  # 10 minutes


def _evict_stale_tokens() -> None:
    """Remove expired and already-used entries from _CHANGE_STORE (lazy eviction)."""
    now = dt.datetime.now(timezone.utc)
    stale = [
        k for k, v in _CHANGE_STORE.items()
        if v["used"] or (now - v["created_at"]).total_seconds() > _TOKEN_TTL_SECONDS
    ]
    for k in stale:
        del _CHANGE_STORE[k]


def _mint_token(user_id: int, kind: str, data: dict) -> str:
    _evict_stale_tokens()
    token = secrets.token_urlsafe(12)
    _CHANGE_STORE[token] = {
        "user_id": user_id,
        "created_at": dt.datetime.now(timezone.utc),
        "used": False,
        "kind": kind,
        "data": data,
    }
    return token


def _validate_token(token: str, user_id: int) -> dict | None:
    """Return the store entry if valid, else None.

    Validates: exists, not expired, not used, user_id matches.
    Returns the entry dict on success, or {"error": "..."} on failure.
    """
    entry = _CHANGE_STORE.get(token)
    if entry is None:
        return {"error": "unknown or already-consumed change token"}

    age = (dt.datetime.now(timezone.utc) - entry["created_at"]).total_seconds()
    if age > _TOKEN_TTL_SECONDS:
        return {"error": "change token has expired"}

    if entry["used"]:
        return {"error": "change token has already been used"}

    if entry["user_id"] != user_id:
        return {"error": "change token belongs to a different user"}

    return None  # valid


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_owned_session(
    session: AsyncSession, charge_id: int, user_id: int
) -> ChargingSession | None:
    """Return the session if owned by user_id, else None (no exceptions)."""
    result = await session.execute(
        select(ChargingSession).where(
            ChargingSession.id == charge_id,
            ChargingSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_owned_location(
    session: AsyncSession, location_id: int, user_id: int
) -> Location | None:
    """Return the location if owned by user_id, else None (no exceptions)."""
    result = await session.execute(
        select(Location).where(
            Location.id == location_id,
            Location.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _format_odometer(km: Optional[float], unit: str) -> Optional[str]:
    if km is None:
        return None
    if unit == "km":
        return f"{round(km):,} km"
    return f"{round(km / _KM_PER_MI):,} mi"


def _session_to_dict(cs: ChargingSession, *, location_name: Optional[str] = None, distance_unit: str = "mi") -> dict:
    return {
        "id": cs.id,
        "date": cs.date,
        "kwh": cs.kwh_added,
        "cost": _format_gbp(cs.cost_pence),       # pounds, e.g. "£9.85"
        "cost_pence": cs.cost_pence,              # raw, for reference
        "soc": {"start": cs.start_soc, "end": cs.end_soc},
        "location_id": cs.location_id,
        "location_name": location_name,
        "network": cs.charge_network,
        "source": cs.source,
        "cost_basis": cs.cost_basis,
        "tariff": _format_rate(cs.tariff_p_per_kwh),  # pence rate, e.g. "7.5p/kWh"
        "tariff_p_per_kwh": cs.tariff_p_per_kwh,
        "notes": cs.notes,
        "charging_type": cs.charging_type,
        "odometer_km": cs.odometer_at_session_km,
        "odometer": _format_odometer(cs.odometer_at_session_km, distance_unit),
    }


# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

_FIND_CHARGES_MAX_LIMIT = 200
_FIND_CHARGES_DEFAULT_LIMIT = 10


def _clamp_limit(
    value: object,
    *,
    default: int = _FIND_CHARGES_DEFAULT_LIMIT,
    maximum: int = _FIND_CHARGES_MAX_LIMIT,
) -> int:
    """Coerce a caller-supplied row limit into ``1 <= n <= maximum``.

    Tokens/agents are authenticated but the limit is otherwise unbounded, so
    a request for ``limit=10_000_000`` would force a huge serialization.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, maximum))


async def find_charges(
    session: AsyncSession,
    user_id: int,
    *,
    query: Optional[str] = None,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    location_id: Optional[int] = None,
    limit: int = 10,
) -> list[dict]:
    """Return recent charges for the user, most-recent first.

    Supports optional filtering by date range and location.
    The `query` param is reserved for future text search; currently ignored.
    """
    try:
        dist_unit_row = (await session.execute(
            select(Setting).where(Setting.key == "distance_unit")
        )).scalar_one_or_none()
        dist_unit = (dist_unit_row.value if dist_unit_row else None) or "mi"

        stmt = (
            select(ChargingSession, Location.name)
            .join(Location, ChargingSession.location_id == Location.id, isouter=True)
            .where(ChargingSession.user_id == user_id)
        )
        if date_from is not None:
            stmt = stmt.where(ChargingSession.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(ChargingSession.date <= date_to)
        if location_id:  # 0/None -> no filter (models pass 0 for unset optionals)
            stmt = stmt.where(ChargingSession.location_id == location_id)
        stmt = stmt.order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
        stmt = stmt.limit(_clamp_limit(limit))

        rows = (await session.execute(stmt)).all()
        return [_session_to_dict(cs, location_name=loc_name, distance_unit=dist_unit) for cs, loc_name in rows]
    except Exception as exc:
        return [{"error": str(exc)}]


async def get_charge(
    session: AsyncSession,
    user_id: int,
    charge_id: int,
) -> dict | None:
    """Return a single charge dict, or None if not found / not owned."""
    try:
        cs = await _get_owned_session(session, charge_id, user_id)
        if cs is None:
            return None

        # Resolve location name
        loc_name = None
        if cs.location_id is not None:
            loc = await session.get(Location, cs.location_id)
            if loc is not None:
                loc_name = loc.name

        dist_unit_row = await session.execute(
            select(Setting).where(Setting.key == "distance_unit")
        )
        dist_unit_row = dist_unit_row.scalar_one_or_none()
        dist_unit = (dist_unit_row.value if dist_unit_row else None) or "mi"
        return _session_to_dict(cs, location_name=loc_name, distance_unit=dist_unit)
    except Exception as exc:
        return {"error": str(exc)}


async def get_insights(
    session: AsyncSession,
    user_id: int,
    *,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
) -> dict:
    """Compose spec-03 aggregators into one insight dict."""
    try:
        totals = await insights_stats.window_totals(
            session, user_id=user_id, lo=date_from, hi=date_to
        )

        split = await insights_stats.home_public_split(
            session, user_id=user_id, date_from=date_from, date_to=date_to
        )

        networks = await insights_stats.network_breakdown(
            session, user_id=user_id, date_from=date_from, date_to=date_to
        )

        # Spend/energy over time (monthly granularity for the overview)
        granularity = "monthly"
        if date_from is not None and date_to is not None:
            granularity = insights_stats.resolve_granularity(date_from, date_to)

        over_time = await insights_stats.spend_energy_over_time(
            session, user_id=user_id,
            date_from=date_from, date_to=date_to,
            granularity=granularity,
        )

        return _annotate_money({
            "totals": totals,
            "home_public_split": split,
            "network_breakdown": networks,
            "spend_energy_over_time": over_time,
            "granularity": granularity,
        })
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# PROPOSE tools (write nothing, return {summary, change_token})
# ---------------------------------------------------------------------------


async def _geocoding_settings(session: AsyncSession) -> dict:
    """Read geocoding settings from the Setting table."""
    keys = ["geocoding_enabled", "geocoding_provider", "geocoding_api_key"]
    rows = (
        await session.execute(select(Setting).where(Setting.key.in_(keys)))
    ).scalars().all()
    return {r.key: r.value for r in rows}


async def propose_create_location(
    session: AsyncSession,
    user_id: int,
    *,
    name: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    address: Optional[str] = None,
) -> dict:
    """Propose creating a new location.

    If explicit coords are given, use them directly.
    If only an address is given, geocode it at propose time so that:
    (a) the summary shows the resolved place, and (b) commit can succeed
    (Location requires coords). Returns an error immediately if geocoding
    yields no result.

    Writes nothing. Returns {summary, change_token}.
    """
    try:
        # Validate: need at least coords or address
        if lat is None and address is None:
            return {"error": "must provide either (lat, lng) or address"}
        if lat is not None and lng is None:
            return {"error": "lng is required when lat is provided"}

        resolved_address: Optional[str] = None

        if lat is None:
            # Address-only path: geocode at propose time
            settings_dict = await _geocoding_settings(session)
            provider = get_provider(settings_dict)
            result = await provider.forward(address)  # type: ignore[arg-type]
            if result is None:
                return {
                    "error": (
                        f"could not geocode {address!r}; provide coordinates"
                    )
                }
            lat = result.lat
            lng = result.lng
            resolved_address = result.address

        # Build data payload (coords now always present)
        data: dict = {"user_id": user_id, "lat": lat, "lng": lng}
        if name is not None:
            data["name"] = name
        if address is not None:
            data["address"] = address

        # Build human-readable summary
        location_desc = name or "new location"
        coord_str = f"({lat:.4f}, {lng:.4f})"
        if resolved_address is not None:
            summary = (
                f"Create location '{location_desc}' at {coord_str} "
                f"(resolved: {resolved_address!r})"
            )
        else:
            summary = f"Create location '{location_desc}' at {coord_str}"

        token = _mint_token(user_id, "create_location", data)
        return {"summary": summary, "change_token": token}
    except Exception as exc:
        return {"error": str(exc)}


async def propose_set_location(
    session: AsyncSession,
    user_id: int,
    *,
    charge_id: int,
    location_id: Optional[int] = None,
    location_name: Optional[str] = None,
) -> dict:
    """Propose setting the location on a charge session.

    Validates session ownership and location ownership (if location_id given).
    Writes nothing. Returns {summary, change_token}.
    """
    try:
        # Validate session ownership
        cs = await _get_owned_session(session, charge_id, user_id)
        if cs is None:
            return {"error": f"charge {charge_id} not found or not owned by this user"}

        # Resolve location
        resolved_location_id: Optional[int] = None
        resolved_location_name: Optional[str] = None

        if location_id:  # 0/None -> no filter (models pass 0 for unset optionals)
            loc = await _get_owned_location(session, location_id, user_id)
            if loc is None:
                return {"error": f"location {location_id} not found or not owned by this user"}
            resolved_location_id = loc.id
            resolved_location_name = loc.name

        elif location_name is not None:
            # Look up by name (user-scoped)
            result = await session.execute(
                select(Location).where(
                    Location.user_id == user_id,
                    Location.name == location_name,
                )
            )
            loc = result.scalar_one_or_none()
            if loc is None:
                return {"error": f"location named {location_name!r} not found"}
            resolved_location_id = loc.id
            resolved_location_name = loc.name

        else:
            return {"error": "must provide either location_id or location_name"}

        summary = (
            f"Set location of charge #{charge_id} "
            f"(date={cs.date}, {cs.kwh_added}kWh) "
            f"to '{resolved_location_name}' (id={resolved_location_id})"
        )

        data = {
            "charge_id": charge_id,
            "location_id": resolved_location_id,
        }
        token = _mint_token(user_id, "set_location", data)
        return {"summary": summary, "change_token": token}
    except Exception as exc:
        return {"error": str(exc)}


async def propose_attach_location(
    session: AsyncSession,
    user_id: int,
    *,
    charge_id: int,
    lat: float,
    lng: float,
) -> dict:
    """Propose attaching a location (from a shared map pin) to a charge.

    Reverse-geocodes the coords at propose time (best-effort) so the summary
    shows the resolved place. On commit, clusters the coords into an existing
    nearby Location or creates a new one, then sets it on the charge. Writes
    nothing here. Returns {summary, change_token}.
    """
    try:
        cs = await _get_owned_session(session, charge_id, user_id)
        if cs is None:
            return {"error": f"charge {charge_id} not found or not owned by this user"}

        place: Optional[str] = None
        try:
            provider = get_provider(await _geocoding_settings(session))
            result = await provider.reverse(lat, lng)
            if result is not None:
                place = result.address
        except Exception:  # noqa: BLE001 — geocoding is best-effort for the label
            place = None

        data: dict = {"charge_id": charge_id, "lat": lat, "lng": lng}
        if place:
            data["name"] = place

        where = place or f"({lat:.4f}, {lng:.4f})"
        summary = (
            f"Attach location {where} to charge #{charge_id} "
            f"(date={cs.date}, {cs.kwh_added}kWh)"
        )
        token = _mint_token(user_id, "attach_location", data)
        return {"summary": summary, "change_token": token}
    except Exception as exc:
        return {"error": str(exc)}


async def propose_edit_charge(
    session: AsyncSession,
    user_id: int,
    *,
    charge_id: int,
    kwh: Optional[float] = None,
    price_p_per_kwh: Optional[float] = None,
    total_cost_p: Optional[int] = None,
    start_soc: Optional[int] = None,
    end_soc: Optional[int] = None,
    date: Optional[dt.date] = None,
    network: Optional[str] = None,
    notes: Optional[str] = None,
    odometer: Optional[float] = None,
    odometer_unit: Optional[str] = None,
) -> dict:
    """Propose editing fields on a charge session.

    Validates ownership. Writes nothing. Returns {summary, change_token}.
    """
    try:
        cs = await _get_owned_session(session, charge_id, user_id)
        if cs is None:
            return {"error": f"charge {charge_id} not found or not owned by this user"}

        # Build data for the pending change
        data: dict = {"charge_id": charge_id}
        changes: list[str] = []

        if kwh is not None:
            data["kwh"] = kwh
            changes.append(f"kWh {cs.kwh_added} → {kwh}")
        if price_p_per_kwh is not None:
            data["price_p_per_kwh"] = price_p_per_kwh
            changes.append(f"rate → {price_p_per_kwh}p/kWh")
        if total_cost_p is not None:
            data["total_cost_p"] = total_cost_p
            changes.append(f"total cost → {total_cost_p}p")
        if start_soc is not None:
            data["start_soc"] = start_soc
            changes.append(f"start SoC → {start_soc}%")
        if end_soc is not None:
            data["end_soc"] = end_soc
            changes.append(f"end SoC → {end_soc}%")
        if date is not None:
            data["date"] = date.isoformat()
            changes.append(f"date → {date}")
        if network is not None:
            data["network"] = network
            changes.append(f"network → {network!r}")
        if notes is not None:
            data["notes"] = notes
            changes.append(f"notes → {notes!r}")

        if odometer is not None:
            # Resolve unit: use odometer_unit if given, else read distance_unit setting
            unit = (odometer_unit or "").lower().strip()
            if unit not in ("mi", "km"):
                # Read from Setting table
                result = await session.execute(
                    select(Setting).where(Setting.key == "distance_unit")
                )
                setting_row = result.scalar_one_or_none()
                unit = (setting_row.value if setting_row else None) or "mi"
            odometer_km = odometer if unit == "km" else odometer * _KM_PER_MI
            data["odometer_km"] = odometer_km
            changes.append(f"odometer → {odometer} {unit}")

        if not changes:
            return {"error": "no changes specified"}

        summary = (
            f"Edit charge #{charge_id} (date={cs.date}, {cs.kwh_added}kWh): "
            + "; ".join(changes)
        )

        token = _mint_token(user_id, "edit_charge", data)
        return {"summary": summary, "change_token": token}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# COMMIT
# ---------------------------------------------------------------------------

# Override fields: editing these means override_changed=True for apply_cost
_OVERRIDE_FIELDS = frozenset({"price_p_per_kwh", "total_cost_p"})


async def commit_change(
    session: AsyncSession,
    user_id: int,
    change_token: str,
) -> dict:
    """Apply a pending change.

    Rejects if:
    - token unknown
    - token expired (> TTL)
    - token already used (single-use)
    - stored user_id != caller (cross-user)

    Applies the change and marks the token as used.
    Returns {"ok": True, ...} on success, {"error": "..."} on failure.
    """
    error = _validate_token(change_token, user_id)
    if error is not None:
        return error

    entry = _CHANGE_STORE[change_token]
    kind = entry["kind"]
    data = entry["data"]

    try:
        result = await _apply_change(session, user_id, kind, data)
        # Mark token as consumed ONLY after successful application
        _CHANGE_STORE[change_token]["used"] = True
        return result
    except Exception as exc:
        return {"error": f"commit failed: {exc}"}


async def _apply_change(
    session: AsyncSession, user_id: int, kind: str, data: dict
) -> dict:
    """Dispatch and apply the change payload."""

    if kind == "create_location":
        return await _apply_create_location(session, user_id, data)
    elif kind == "set_location":
        return await _apply_set_location(session, user_id, data)
    elif kind == "attach_location":
        return await _apply_attach_location(session, user_id, data)
    elif kind == "edit_charge":
        return await _apply_edit_charge(session, user_id, data)
    else:
        return {"error": f"unknown change kind: {kind}"}


async def attach_coords_to_charge(
    session: AsyncSession, user_id: int, *, charge_id: int,
    lat: float, lng: float, name: Optional[str] = None,
) -> Optional[Location]:
    """Cluster coords into an existing nearby Location (or create one) and set
    it on the charge, re-deriving cost under the freeze invariant. Flushes but
    does NOT commit — the caller owns the transaction. Returns the Location, or
    None if the charge is not owned. Shared by the attach_location change and
    the Telegram Save-time auto-attach of a held pin."""
    cs = await _get_owned_session(session, charge_id, user_id)
    if cs is None:
        return None
    loc, created = await find_or_create_location(session, user_id, lat, lng)
    if created and name and not loc.name:
        loc.name = name
    cs.location_id = loc.id
    await apply_cost(session, cs, first_compute=False, override_changed=False)
    await session.flush()
    return loc


async def _apply_attach_location(
    session: AsyncSession, user_id: int, data: dict
) -> dict:
    loc = await attach_coords_to_charge(
        session, user_id, charge_id=data["charge_id"],
        lat=data["lat"], lng=data["lng"], name=data.get("name"),
    )
    if loc is None:
        return {"error": f"charge {data['charge_id']} not found or not owned by this user"}
    await session.commit()
    return {"ok": True, "charge_id": data["charge_id"], "location_id": loc.id, "name": loc.name}


async def _apply_create_location(
    session: AsyncSession, user_id: int, data: dict
) -> dict:
    name = data.get("name")
    lat = data.get("lat")
    lng = data.get("lng")
    address = data.get("address")

    if lat is not None and lng is not None:
        # Explicit coords: use find_or_create_location (clusters within radius)
        loc, created = await find_or_create_location(session, user_id, lat, lng)
        if created and name:
            loc.name = name
        elif not created and name and loc.name is None:
            loc.name = name
        await session.commit()
        await session.refresh(loc)
        return {"ok": True, "location_id": loc.id, "created": created, "name": loc.name}
    else:
        # Address-only: create a location with no coords (geocoding is out of scope here)
        # We create a placeholder location — real implementations would geocode first.
        # Per spec, geocoding at propose time is optional when address is given.
        # We store address on the location row if the model supported it directly.
        # Since Location requires centroid_lat/lng, we can't create without coords.
        # Return an error guiding the caller.
        return {
            "error": "address-only location creation requires geocoding — "
                     "provide lat/lng instead, or geocode the address first"
        }


async def _apply_set_location(
    session: AsyncSession, user_id: int, data: dict
) -> dict:
    charge_id: int = data["charge_id"]
    location_id: int = data["location_id"]

    # Re-validate ownership at commit time (could have changed since propose)
    cs = await _get_owned_session(session, charge_id, user_id)
    if cs is None:
        return {"error": f"charge {charge_id} not found or not owned by this user"}

    loc = await _get_owned_location(session, location_id, user_id)
    if loc is None:
        return {"error": f"location {location_id} not found or not owned by this user"}

    cs.location_id = location_id
    # Location change is cost-affecting; re-derive but honour freeze invariant
    await apply_cost(session, cs, first_compute=False, override_changed=False)
    await session.commit()
    await session.refresh(cs)

    return {"ok": True, "charge_id": charge_id, "location_id": location_id}


async def _apply_edit_charge(
    session: AsyncSession, user_id: int, data: dict
) -> dict:
    charge_id: int = data["charge_id"]

    cs = await _get_owned_session(session, charge_id, user_id)
    if cs is None:
        return {"error": f"charge {charge_id} not found or not owned by this user"}

    # Detect which fields are present in the payload
    override_changed = bool(_OVERRIDE_FIELDS & data.keys())
    cost_dirty = False

    if "kwh" in data:
        cs.kwh_added = data["kwh"]
        cost_dirty = True

    if "price_p_per_kwh" in data:
        cs.cost_per_kwh_override_p = data["price_p_per_kwh"]
        cost_dirty = True

    if "total_cost_p" in data:
        cs.total_cost_pence_override = data["total_cost_p"]
        cost_dirty = True

    if "start_soc" in data:
        cs.start_soc = data["start_soc"]

    if "end_soc" in data:
        cs.end_soc = data["end_soc"]

    if "date" in data:
        import datetime as _dt
        cs.date = _dt.date.fromisoformat(data["date"])

    if "network" in data:
        cs.charge_network = data["network"]

    if "notes" in data:
        cs.notes = data["notes"]

    if "odometer_km" in data:
        cs.odometer_at_session_km = data["odometer_km"]

    if cost_dirty:
        await apply_cost(session, cs, first_compute=False, override_changed=override_changed)

    await session.commit()
    await session.refresh(cs)

    return {"ok": True, "charge_id": charge_id}
