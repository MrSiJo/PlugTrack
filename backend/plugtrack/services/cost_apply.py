"""Cost-freezing-aware apply service.

Extracted from ``api/routes/sessions.py:_apply_cost`` so that the web route
and future MCP/bot ``edit_charge`` tool share a single cost path.

The freeze invariant (spec §3.3 / spec 01):

  On an EDIT of an existing rate-derived session (``home_rate``,
  ``location_rate``, ``location_free``) where no override field changed and a
  tariff is already stored, re-scale at that frozen tariff — a global /
  location config change never silently re-rates a stored charge.

  Otherwise (create/confirm; an explicit override change; an override basis; or
  no stored tariff — the legacy guard) derive from source via the
  cost-precedence rule.  Override bases re-derive from their own frozen
  override columns, which is correct.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Location, Setting
from ..models.charging_session import ChargingSession
from .cost import compute_session_cost


async def _get_owned_location(
    session: AsyncSession, location_id: Optional[int], user_id: int
) -> Optional[Location]:
    if location_id is None:
        return None
    result = await session.execute(
        select(Location).where(
            Location.id == location_id, Location.user_id == user_id
        )
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=400, detail="location not found")
    return loc


async def _home_rate(session: AsyncSession) -> float:
    result = await session.execute(
        select(Setting).where(Setting.key == "default_home_rate_p_per_kwh")
    )
    row = result.scalar_one_or_none()
    if row is None or row.value is None:
        return 0.0
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return 0.0


async def apply_cost(
    session: AsyncSession,
    cs: ChargingSession,
    *,
    first_compute: bool = True,
    override_changed: bool = False,
) -> None:
    """Resolve cost, honouring the freeze invariant.

    On an EDIT of an existing rate-derived session (``home_rate``,
    ``location_rate``, ``location_free``) where no override field changed and a
    tariff is already stored, re-scale at that frozen tariff — a global /
    location config change never silently re-rates a stored charge.

    Otherwise (create/confirm; an explicit override change; an override
    basis; or no stored tariff — the legacy guard) derive from source via
    the cost-precedence rule.  Override bases re-derive from their own frozen
    override columns, which is correct.

    The caller's ``user_id`` is taken from ``cs.user_id`` so the location
    ownership check is always scoped to the session owner.
    """
    rate_derived = cs.cost_basis in ("home_rate", "location_rate", "location_free")
    if (
        not first_compute
        and not override_changed
        and rate_derived
        and cs.tariff_p_per_kwh is not None
    ):
        cs.cost_pence = round(cs.kwh_added * cs.tariff_p_per_kwh)
        return

    location = await _get_owned_location(session, cs.location_id, cs.user_id)
    home_rate = await _home_rate(session)
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=cs.kwh_added,
        location=location,
        session_overrides={
            "cost_per_kwh_override_p": cs.cost_per_kwh_override_p,
            "total_cost_pence_override": cs.total_cost_pence_override,
        },
        settings_default_home_rate_p_per_kwh=home_rate,
    )
    cs.cost_pence = cost_pence
    cs.cost_basis = cost_basis
    cs.tariff_p_per_kwh = tariff
