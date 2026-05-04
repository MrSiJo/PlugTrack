"""Location label endpoint — first-label flow.

PATCH /api/locations/{id}/label sets the location's `name`, `is_home`,
`is_free`, and `default_cost_per_kwh_p`. Refuses if `name` is already
set (returns 409). The `Location admin` page in Phase 5 handles
subsequent edits.

On a successful first-label, every past charging_session linked to the
location with `cost_basis = 'home_rate'` is recomputed against the new
location config (spec §3.3 lines 167–180). Sessions with overrides
(`cost_basis IN ('override_total', 'override_per_kwh')`) are NEVER
touched — user overrides are sacred. Sessions already on
`location_rate` / `location_free` from a prior label step (shouldn't
happen on first-label, but is defensive) are also left alone.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import ChargingSession, Location, Setting
from ...services.cost import compute_session_cost


router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationLabelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_home: bool = False
    is_free: bool = False
    default_cost_per_kwh_p: Optional[float] = Field(default=None, ge=0)


class LocationPayload(BaseModel):
    id: int
    name: Optional[str]
    centroid_lat: float
    centroid_lng: float
    radius_m: int
    is_home: bool
    is_free: bool
    default_cost_per_kwh_p: Optional[float]
    address: Optional[str]


class LocationLabelResponse(BaseModel):
    location: LocationPayload
    sessions_recomputed_count: int


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _to_payload(loc: Location) -> LocationPayload:
    return LocationPayload(
        id=loc.id,
        name=loc.name,
        centroid_lat=loc.centroid_lat,
        centroid_lng=loc.centroid_lng,
        radius_m=loc.radius_m,
        is_home=loc.is_home,
        is_free=loc.is_free,
        default_cost_per_kwh_p=loc.default_cost_per_kwh_p,
        address=loc.address,
    )


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


@router.patch("/{location_id}/label", response_model=LocationLabelResponse)
async def label_location(
    location_id: int,
    request: Request,
    body: LocationLabelRequest,
    session: AsyncSession = Depends(get_db),
) -> LocationLabelResponse:
    user_id = _user_id(request)

    result = await session.execute(
        select(Location).where(
            Location.id == location_id, Location.user_id == user_id
        )
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="location not found")

    # First-label only. Subsequent edits go via the (Phase 5) admin
    # endpoint with explicit "recalculate past sessions" confirmation.
    if loc.name is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "location already labelled — use the locations admin "
                "endpoint to edit"
            ),
        )

    loc.name = body.name
    loc.is_home = body.is_home
    loc.is_free = body.is_free
    loc.default_cost_per_kwh_p = body.default_cost_per_kwh_p

    # Retro-recompute: only sessions on `home_rate` (the global
    # fallback). Override-based costs are sacred.
    home_rate = await _home_rate(session)
    sessions_to_recompute = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.location_id == loc.id,
                ChargingSession.user_id == user_id,
                ChargingSession.cost_basis == "home_rate",
            )
        )
    ).scalars().all()

    recomputed = 0
    for cs in sessions_to_recompute:
        new_cost, new_basis, new_tariff = compute_session_cost(
            kwh_added=cs.kwh_added,
            location=loc,
            session_overrides={
                "cost_per_kwh_override_p": cs.cost_per_kwh_override_p,
                "total_cost_pence_override": cs.total_cost_pence_override,
            },
            settings_default_home_rate_p_per_kwh=home_rate,
        )
        cs.cost_pence = new_cost
        cs.cost_basis = new_basis
        cs.tariff_p_per_kwh = new_tariff
        recomputed += 1

    await session.commit()
    await session.refresh(loc)

    return LocationLabelResponse(
        location=_to_payload(loc),
        sessions_recomputed_count=recomputed,
    )
