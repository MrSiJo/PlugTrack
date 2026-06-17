# backend/plugtrack/services/screenshot_commit.py
"""Persist a MergedSession as a ChargingSession.

Public charges carry a real total -> total_cost_pence_override (cost_basis
'override_total', sacred). Location captured as text (network/label/notes);
location_id left null (cost comes from the override, not a location rate).
Dedupe: skip if an existing session for the same car overlaps in time and
matches energy within tolerance.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession
from .screenshot_correlation import MergedSession

DEDUPE_TIME_MIN = 30
DEDUPE_KWH_TOL = 0.5


async def _distance_unit(session: AsyncSession) -> str:
    """The user-facing distance unit ('mi'/'km') from settings; default 'mi'."""
    from ..models import Setting
    row = (
        await session.execute(select(Setting).where(Setting.key == "distance_unit"))
    ).scalar_one_or_none()
    return (row.value or "mi").lower() if row and row.value else "mi"


async def _is_duplicate(session: AsyncSession, *, car_id: int, merged: MergedSession) -> bool:
    lo = merged.start_at - timedelta(minutes=DEDUPE_TIME_MIN)
    hi = merged.start_at + timedelta(minutes=DEDUPE_TIME_MIN)
    rows = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.car_id == car_id,
                ChargingSession.charge_start_at.is_not(None),
                ChargingSession.charge_start_at >= lo,
                ChargingSession.charge_start_at <= hi,
            )
        )
    ).scalars().all()
    target = merged.energy_kwh
    for r in rows:
        if target is None or abs((r.kwh_added or 0.0) - target) <= DEDUPE_KWH_TOL:
            return True
    return False


async def match_location_by_name(
    session: AsyncSession, *, user_id: int, name: Optional[str]
) -> Optional[int]:
    if not name or not name.strip():
        return None
    from ..models import Location
    row = (
        await session.execute(
            select(Location.id).where(
                Location.user_id == user_id,
                func.lower(Location.name) == name.strip().lower(),
            )
        )
    ).scalar_one_or_none()
    return row


async def _build_session(
    session: AsyncSession, *, user_id: int, car_id: int, merged: MergedSession
) -> ChargingSession:
    """Build the ChargingSession a Save would create — classify type, match a
    named location, resolve delivered-vs-banked kWh, and apply cost. Does NOT
    add it to the session or flush. Shared by commit (persists) and preview
    (renders the confirm card)."""
    from ..api.routes.sessions import _apply_cost, _derive_kwh_calculated  # reuse

    has_network = bool(merged.network) or merged.cost_total_pence is not None
    has_soc = merged.soc_start is not None or merged.soc_end is not None
    if has_network:
        charging_type = "dc"
    elif has_soc:
        charging_type = "ac"        # home / AC
    else:
        charging_type = "unknown"

    label = merged.location_name
    notes = merged.location_address
    cs = ChargingSession(
        user_id=user_id,
        car_id=car_id,
        date=merged.start_at.date(),
        charge_start_at=merged.start_at,
        charge_end_at=merged.end_at,
        start_soc=merged.soc_start if merged.soc_start is not None else 0,
        end_soc=merged.soc_end if merged.soc_end is not None else 0,
        kwh_added=merged.energy_kwh if merged.energy_kwh is not None else 0.0,
        charging_type=charging_type,
        charging_mode="unknown",
        total_cost_pence_override=merged.cost_total_pence,
        cost_per_kwh_override_p=(
            merged.cost_per_kwh_pence if merged.cost_total_pence is None else None
        ),
        charge_network=merged.network,
        user_label=label[:128] if label else None,
        notes=notes[:512] if notes else None,
        power_curve=None,
        source="import",
    )

    # Match a named location (e.g. caption "home") for rate-based costing.
    cs.location_id = await match_location_by_name(session, user_id=user_id, name=merged.location_name)

    # Banked energy from SoC (kwh_calculated). For home/metered-less charges,
    # promote it to kwh_added so cost (delivered-based) and totals work.
    await _derive_kwh_calculated(session, cs)
    if (cs.kwh_added is None or cs.kwh_added == 0.0) and cs.kwh_calculated:
        cs.kwh_added = cs.kwh_calculated

    await _apply_cost(session, cs, user_id)

    if merged.odometer is not None:
        from .mileage_tracking import miles_to_km
        unit = (merged.odometer_unit or await _distance_unit(session)).lower()
        is_km = unit.startswith("k")
        cs.odometer_at_session_km = (
            float(merged.odometer) if is_km else miles_to_km(merged.odometer)
        )

    return cs


async def preview_merged_session(
    session: AsyncSession, *, user_id: int, car_id: int, merged: MergedSession
) -> ChargingSession:
    """The unsaved ChargingSession a Save would produce (kwh_added, cost_pence,
    cost_basis, charging_type), for the confirm card. Ignores dedupe; persists
    nothing."""
    return await _build_session(session, user_id=user_id, car_id=car_id, merged=merged)


async def commit_merged_session(
    session: AsyncSession, *, user_id: int, car_id: int, merged: MergedSession
) -> Optional[ChargingSession]:
    if await _is_duplicate(session, car_id=car_id, merged=merged):
        return None
    cs = await _build_session(session, user_id=user_id, car_id=car_id, merged=merged)
    session.add(cs)
    await session.flush()
    return cs
