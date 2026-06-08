"""Location endpoints — first-label flow + Phase 5 admin CRUD.

Two distinct mutating verbs by design:

- `PATCH /api/locations/{id}/label` is the **first-label** entry point.
  Refuses to run twice (409 if `name` is already set). Retro-recomputes
  every past `home_rate` session for the location against the new
  config (spec §3.3 lines 167–180).

- `PUT  /api/locations/{id}` is the **admin edit** entry point. **Forward-
  going only** — never touches existing sessions. The user must press
  the explicit `POST /api/locations/{id}/recalculate-past-costs` button
  to re-apply the rule to historical rows. This avoids surprise
  silent-rewrites of accounting data.

Plus list / merge / delete:
- `GET    /api/locations` — list with aggregated visit + spend stats.
- `POST   /api/locations/{id}/merge` — atomically redirect every
  charging_session + plug_in_record onto a target id, sum visit_count,
  delete source. Recomputes only when target's cost config differs.
- `DELETE /api/locations/{id}` — soft-detach (sessions get
  location_id=NULL), then delete. Sessions auto-fall-back to the global
  home rate via the cost-precedence rule.

User-overrides (`override_total` / `override_per_kwh`) are sacred and
NEVER touched by any of these endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import ChargingSession, Location, PlugInRecord, Setting
from ...services.cost import compute_session_cost


router = APIRouter(prefix="/api/locations", tags=["locations"])


# Cost basis values that user-overrides own — never auto-recomputed.
_OVERRIDE_BASES = ("override_total", "override_per_kwh")


class LocationLabelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_home: bool = False
    is_free: bool = False
    default_cost_per_kwh_p: Optional[float] = Field(default=None, ge=0)
    default_charge_network: Optional[str] = Field(default=None, max_length=64)


class LocationPayload(BaseModel):
    id: int
    name: Optional[str]
    centroid_lat: float
    centroid_lng: float
    radius_m: int
    is_home: bool
    is_free: bool
    default_cost_per_kwh_p: Optional[float]
    default_charge_network: Optional[str]
    address: Optional[str]


class LocationListPayload(BaseModel):
    """Extended payload for the admin list view — includes aggregates."""

    id: int
    name: Optional[str]
    centroid_lat: float
    centroid_lng: float
    radius_m: int
    is_home: bool
    is_free: bool
    default_cost_per_kwh_p: Optional[float]
    default_charge_network: Optional[str]
    address: Optional[str]
    visit_count: int
    total_kwh: float
    total_cost_pence: int
    last_visited_at: Optional[str]


class LocationUpdateRequest(BaseModel):
    """Admin edit — forward-going only.

    Excludes centroid fields (set by clustering, not user-editable). Does
    NOT trigger retro-recompute; the caller must press the explicit
    "Recalculate past costs" button.
    """

    name: Optional[str] = Field(default=None, max_length=128)
    is_home: Optional[bool] = None
    is_free: Optional[bool] = None
    default_cost_per_kwh_p: Optional[float] = Field(default=None, ge=0)
    default_charge_network: Optional[str] = Field(default=None, max_length=64)
    radius_m: Optional[int] = Field(default=None, ge=1, le=10_000)


class LocationCreateRequest(BaseModel):
    """Manual location creation — the user supplies the centroid directly
    (map-click or typed lat/lng) instead of waiting for clustering.

    Unlike clustering-created rows, `centroid_lat`/`centroid_lng` are
    required here. Cost config is optional and applies forward-going only
    (there is no history to recompute on a brand-new location).
    """

    name: Optional[str] = Field(default=None, max_length=128)
    centroid_lat: float = Field(ge=-90, le=90)
    centroid_lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=100, ge=1, le=10_000)
    is_home: bool = False
    is_free: bool = False
    default_cost_per_kwh_p: Optional[float] = Field(default=None, ge=0)
    default_charge_network: Optional[str] = Field(default=None, max_length=64)


class LocationMergeRequest(BaseModel):
    target_id: int


class LocationLabelResponse(BaseModel):
    location: LocationPayload
    sessions_recomputed_count: int


class RecalculateResponse(BaseModel):
    sessions_recomputed_count: int


class MergeResponse(BaseModel):
    sessions_redirected: int
    plug_ins_redirected: int
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
        default_charge_network=loc.default_charge_network,
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


async def _backfill_charge_network(
    session: AsyncSession,
    location: Location,
    user_id: int,
) -> int:
    """Set `charge_network` on past sessions of `location` where it's NULL.

    Only fills the gap — never overwrites a user-set network. Returns
    the count touched. No-op when the location has no
    `default_charge_network` configured.
    """
    if not location.default_charge_network:
        return 0
    rows = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.location_id == location.id,
                ChargingSession.user_id == user_id,
                ChargingSession.charge_network.is_(None),
            )
        )
    ).scalars().all()
    for cs in rows:
        cs.charge_network = location.default_charge_network
    return len(rows)


async def _recompute_sessions_for_location(
    session: AsyncSession,
    location: Location,
    user_id: int,
    *,
    bases: tuple[str, ...] = ("home_rate", "location_rate", "location_free"),
) -> int:
    """Re-apply `compute_session_cost` to every session linked to `location`
    whose `cost_basis` is in `bases`.

    Returns the count touched. Override-based costs (`override_total`,
    `override_per_kwh`) are NEVER passed in `bases` from any caller —
    they're sacred per spec §3.3.
    """
    home_rate = await _home_rate(session)
    rows = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.location_id == location.id,
                ChargingSession.user_id == user_id,
                ChargingSession.cost_basis.in_(bases),
            )
        )
    ).scalars().all()

    count = 0
    for cs in rows:
        new_cost, new_basis, new_tariff = compute_session_cost(
            kwh_added=cs.kwh_added,
            location=location,
            session_overrides={
                "cost_per_kwh_override_p": cs.cost_per_kwh_override_p,
                "total_cost_pence_override": cs.total_cost_pence_override,
            },
            settings_default_home_rate_p_per_kwh=home_rate,
        )
        cs.cost_pence = new_cost
        cs.cost_basis = new_basis
        cs.tariff_p_per_kwh = new_tariff
        count += 1
    return count


def _location_cost_config_differs(a: Location, b: Location) -> bool:
    """Two locations differ for cost purposes if any precedence-relevant
    field differs."""
    return (
        a.is_free != b.is_free
        or a.default_cost_per_kwh_p != b.default_cost_per_kwh_p
    )


@router.get("", response_model=list[LocationListPayload])
async def list_locations(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[LocationListPayload]:
    """List the user's locations with aggregated visit + spend stats.

    Aggregates via a single GROUP BY against `charging_session`. Locations
    with no sessions get zeros and a NULL `last_visited_at`. Unlabelled
    locations (`name IS NULL`) sort first so the admin UI surfaces them
    for action.
    """
    user_id = _user_id(request)

    # Aggregate sessions per location.
    agg_stmt = (
        select(
            ChargingSession.location_id,
            func.count(ChargingSession.id).label("visit_count"),
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0).label("total_kwh"),
            func.coalesce(func.sum(ChargingSession.cost_pence), 0).label(
                "total_cost_pence"
            ),
            func.max(ChargingSession.charge_end_at).label("last_visited_at"),
        )
        .where(ChargingSession.user_id == user_id)
        .group_by(ChargingSession.location_id)
    )
    agg_rows = (await session.execute(agg_stmt)).all()
    agg_by_id = {r.location_id: r for r in agg_rows if r.location_id is not None}

    locations = (
        await session.execute(
            select(Location).where(Location.user_id == user_id)
        )
    ).scalars().all()

    out: list[LocationListPayload] = []
    for loc in locations:
        agg = agg_by_id.get(loc.id)
        last_at: Optional[str] = None
        if agg is not None and agg.last_visited_at is not None:
            last_at = agg.last_visited_at.isoformat()
        out.append(
            LocationListPayload(
                id=loc.id,
                name=loc.name,
                centroid_lat=loc.centroid_lat,
                centroid_lng=loc.centroid_lng,
                radius_m=loc.radius_m,
                is_home=loc.is_home,
                is_free=loc.is_free,
                default_cost_per_kwh_p=loc.default_cost_per_kwh_p,
                default_charge_network=loc.default_charge_network,
                address=loc.address,
                visit_count=int(agg.visit_count) if agg is not None else 0,
                total_kwh=float(agg.total_kwh) if agg is not None else 0.0,
                total_cost_pence=int(agg.total_cost_pence) if agg is not None else 0,
                last_visited_at=last_at,
            )
        )

    # Unlabelled locations float to the top so the admin acts on them.
    out.sort(
        key=lambda x: (
            x.name is not None,
            (x.name or "").lower(),
            x.id,
        )
    )
    return out


@router.post("", response_model=LocationPayload, status_code=201)
async def create_location(
    request: Request,
    body: LocationCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> LocationPayload:
    """Create a location manually from a supplied centroid.

    Forward-going only by definition — a new location has no past
    sessions, so there is nothing to recompute. An empty/whitespace
    `name` is normalised to NULL so the row still surfaces under the
    "needs labelling" sort if the user skipped naming it.
    """
    user_id = _user_id(request)

    name = body.name.strip() if body.name else None
    network = (
        body.default_charge_network.strip()
        if body.default_charge_network and body.default_charge_network.strip()
        else None
    )

    loc = Location(
        user_id=user_id,
        name=name or None,
        centroid_lat=body.centroid_lat,
        centroid_lng=body.centroid_lng,
        radius_m=body.radius_m,
        is_home=body.is_home,
        is_free=body.is_free,
        default_cost_per_kwh_p=body.default_cost_per_kwh_p,
        default_charge_network=network,
        visit_count=0,
    )
    session.add(loc)
    await session.commit()
    await session.refresh(loc)
    return _to_payload(loc)


@router.put("/{location_id}", response_model=LocationPayload)
async def update_location(
    location_id: int,
    request: Request,
    body: LocationUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> LocationPayload:
    """Forward-going edit. Does NOT recompute past sessions.

    To re-apply this location's cost config to history, the caller must
    press the explicit "Recalculate past costs" button which hits
    `POST /api/locations/{id}/recalculate-past-costs`.
    """
    user_id = _user_id(request)
    result = await session.execute(
        select(Location).where(
            Location.id == location_id, Location.user_id == user_id
        )
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="location not found")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(loc, k, v)

    await session.commit()
    await session.refresh(loc)
    return _to_payload(loc)


@router.post(
    "/{location_id}/recalculate-past-costs",
    response_model=RecalculateResponse,
)
async def recalculate_past_costs(
    location_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> RecalculateResponse:
    """Re-apply `compute_session_cost` to all non-override sessions
    linked to this location.

    Override-based costs (`override_total` / `override_per_kwh`) are
    NEVER touched — user overrides are sacred per spec §3.3.
    """
    user_id = _user_id(request)
    result = await session.execute(
        select(Location).where(
            Location.id == location_id, Location.user_id == user_id
        )
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="location not found")

    count = await _recompute_sessions_for_location(session, loc, user_id)
    await session.commit()
    return RecalculateResponse(sessions_recomputed_count=count)


@router.post("/{location_id}/merge", response_model=MergeResponse)
async def merge_locations(
    location_id: int,
    request: Request,
    body: LocationMergeRequest,
    session: AsyncSession = Depends(get_db),
) -> MergeResponse:
    """Atomically redirect every session + plug-in from `location_id`
    onto `body.target_id`, sum visit_count, delete the source row.

    Recomputes only when the target's cost config differs from the
    source — if both have the same `is_free` + `default_cost_per_kwh_p`
    the per-session cost would be unchanged. Override-based sessions
    are never recomputed.
    """
    user_id = _user_id(request)
    if body.target_id == location_id:
        raise HTTPException(status_code=400, detail="cannot merge a location into itself")

    source = (
        await session.execute(
            select(Location).where(
                Location.id == location_id, Location.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="source location not found")
    target = (
        await session.execute(
            select(Location).where(
                Location.id == body.target_id, Location.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target location not found")

    cost_dirty = _location_cost_config_differs(source, target)

    sessions = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.location_id == source.id,
                ChargingSession.user_id == user_id,
            )
        )
    ).scalars().all()
    for cs in sessions:
        cs.location_id = target.id

    plug_ins = (
        await session.execute(
            select(PlugInRecord).where(
                PlugInRecord.location_id == source.id,
                PlugInRecord.user_id == user_id,
            )
        )
    ).scalars().all()
    for pir in plug_ins:
        pir.location_id = target.id

    target.visit_count = int(target.visit_count or 0) + int(source.visit_count or 0)

    recomputed = 0
    if cost_dirty:
        recomputed = await _recompute_sessions_for_location(
            session, target, user_id
        )

    await session.delete(source)
    await session.commit()

    return MergeResponse(
        sessions_redirected=len(sessions),
        plug_ins_redirected=len(plug_ins),
        sessions_recomputed_count=recomputed,
    )


@router.delete("/{location_id}", status_code=204)
async def delete_location(
    location_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Detach all linked sessions + plug-ins (set `location_id=NULL`),
    then delete the location row.

    Sessions auto-fall-back to the global home rate via the cost-precedence
    rule on the next read — but cost_pence rows are NOT recomputed here
    by design (that's an explicit user action via the recalculate
    button). Override-based costs naturally remain sacred.
    """
    user_id = _user_id(request)
    result = await session.execute(
        select(Location).where(
            Location.id == location_id, Location.user_id == user_id
        )
    )
    loc = result.scalar_one_or_none()
    if loc is None:
        raise HTTPException(status_code=404, detail="location not found")

    sessions = (
        await session.execute(
            select(ChargingSession).where(
                ChargingSession.location_id == loc.id,
                ChargingSession.user_id == user_id,
            )
        )
    ).scalars().all()
    for cs in sessions:
        cs.location_id = None

    plug_ins = (
        await session.execute(
            select(PlugInRecord).where(
                PlugInRecord.location_id == loc.id,
                PlugInRecord.user_id == user_id,
            )
        )
    ).scalars().all()
    for pir in plug_ins:
        pir.location_id = None

    await session.delete(loc)
    await session.commit()
    from fastapi import Response
    return Response(status_code=204)


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
    loc.default_charge_network = body.default_charge_network

    # Retro-recompute: only sessions on `home_rate` (the global
    # fallback). Override-based costs are sacred.
    recomputed = await _recompute_sessions_for_location(
        session, loc, user_id, bases=("home_rate",)
    )

    # Back-fill the network on past sessions that don't have one yet.
    # Mirrors the cost back-fill: forward and back, but only into NULL
    # gaps — user-set networks are never overwritten.
    await _backfill_charge_network(session, loc, user_id)

    await session.commit()
    await session.refresh(loc)

    return LocationLabelResponse(
        location=_to_payload(loc),
        sessions_recomputed_count=recomputed,
    )
