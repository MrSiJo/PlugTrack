"""Charging-session CRUD routes (manual entry only in Phase 3).

Auth + CSRF enforced by middleware. All queries filter by
`request.state.user_id` for multi-user isolation.

`compute_session_cost` is invoked on save for any new session and on
update when any cost-affecting field changes (kwh_added, location_id,
or either override). Override fields are sacred — re-syncs in Phase 4
must never overwrite them.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car, ChargingSession, Location
from ...services.cost_apply import apply_cost
from ...services.session_metrics import (
    compute_savings_for_sessions,
    compute_session_metrics,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# Cost-affecting fields. If any of these changes on update, recompute.
_COST_AFFECTING = frozenset(
    {
        "kwh_added",
        "location_id",
        "cost_per_kwh_override_p",
        "total_cost_pence_override",
    }
)

# Override fields whose explicit change re-derives cost from source on edit.
# Any OTHER edit of a rate-derived session re-scales at the frozen tariff.
_OVERRIDE_FIELDS = frozenset(
    {
        "cost_per_kwh_override_p",
        "total_cost_pence_override",
    }
)

# SoC fields that affect kwh_calculated (energy banked in the pack).
# Distinct from `kwh_added` (the charger's delivered reading) so
# efficiency_percent in SessionMetrics can mean something.
_SOC_AFFECTING = frozenset({"start_soc", "end_soc"})


async def _derive_kwh_calculated(
    session: AsyncSession, cs: ChargingSession
) -> None:
    """Set cs.kwh_calculated from (Δsoc / 100) × car.battery_kwh.

    No-op when SoC is missing or the car can't be found. Clamped to >=0
    so a malformed entry (end < start) doesn't write a negative value.
    """
    if cs.start_soc is None or cs.end_soc is None:
        return
    car = await session.get(Car, cs.car_id)
    if car is None:
        return
    delta = cs.end_soc - cs.start_soc
    if delta < 0:
        cs.kwh_calculated = 0.0
        return
    cs.kwh_calculated = round(delta / 100.0 * float(car.battery_kwh), 2)


class SessionMetricsPayload(BaseModel):
    miles_since_previous: Optional[float]
    # Genuine odometer-measured miles since the previous odometer-bearing
    # charge. Informational only — does not feed the savings calculation.
    # None when no prior odometer reading exists.
    measured_miles_since_previous: Optional[float] = None
    cost_per_mile_p: Optional[float]
    petrol_ppm: Optional[float]
    petrol_equivalent_cost_p: Optional[int]
    savings_vs_petrol_p: Optional[int]
    petrol_price_p_per_litre: Optional[float]
    petrol_mpg: Optional[float]
    chain_session_ids: list[int] = []
    chain_total_cost_pence: Optional[int] = None
    chain_anchor_id: Optional[int] = None
    # Charge-mechanics derived fields. Any may be None when inputs are
    # missing — manual sessions typically have no power_curve so
    # peak_power_kw is None; sessions without start/end timestamps have
    # no duration or avg power.
    range_added_miles: Optional[float] = None
    duration_minutes: Optional[int] = None
    average_power_kw: Optional[float] = None
    peak_power_kw: Optional[float] = None
    efficiency_percent: Optional[float] = None
    # Real-world efficiency (mi/kWh) used for this session's estimates, plus
    # whether it came from observed odometer history or the nominal spec.
    efficiency_mi_per_kwh: Optional[float] = None
    efficiency_basis: Optional[str] = None


class SessionPayload(BaseModel):
    id: int
    user_id: int
    car_id: int
    plug_in_record_id: Optional[int]
    date: date_cls
    charge_start_at: Optional[datetime]
    charge_end_at: Optional[datetime]
    start_soc: int
    end_soc: int
    kwh_added: float
    kwh_calculated: Optional[float] = None
    odometer_at_session_km: Optional[float]
    charging_type: str
    charging_mode: str
    battery_care: Optional[bool] = None
    max_charge_current: Optional[str] = None
    actual_charge_seconds: Optional[int] = None
    interrupted: bool
    cost_pence: Optional[int]
    cost_basis: str
    tariff_p_per_kwh: Optional[float]
    cost_per_kwh_override_p: Optional[float]
    total_cost_pence_override: Optional[int]
    location_id: Optional[int]
    location_name: Optional[str] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    user_label: Optional[str]
    charge_network: Optional[str]
    notes: Optional[str]
    source: str
    telematics_session_id: Optional[str]
    # Live charge curve as `[[delta_seconds, soc, power_kw], ...]`.
    # Written by the sync worker on every poll while CHARGING so the
    # session detail page can plot SoC + power as the charge progresses.
    # NULL on manual sessions and pre-Phase-4 historic rows.
    power_curve: Optional[list] = None
    # True when `power_curve` is a vision-extracted approximation (a telegram
    # screenshot's app graph) rather than a measured synthesis curve. The
    # frontend dashes + badges an approximate curve.
    power_curve_approximate: bool = False
    saved_vs_petrol_p: Optional[int] = None
    comparison_basis: Optional[str] = None
    breakeven_p_per_kwh: Optional[float] = None
    metrics: Optional[SessionMetricsPayload] = None


class SessionCreateRequest(BaseModel):
    car_id: int
    date: date_cls
    start_soc: int = Field(ge=0, le=100)
    end_soc: int = Field(ge=0, le=100)
    kwh_added: float = Field(gt=0, lt=1000)
    odometer_at_session_km: Optional[float] = Field(default=None, ge=0)
    charge_start_at: Optional[datetime] = None
    charge_end_at: Optional[datetime] = None
    location_id: Optional[int] = None
    charging_type: str = Field(default="unknown", max_length=16)
    charging_mode: str = Field(default="unknown", max_length=16)
    cost_per_kwh_override_p: Optional[float] = Field(default=None, ge=0)
    total_cost_pence_override: Optional[int] = Field(default=None, ge=0)
    charge_network: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = Field(default=None, max_length=512)
    user_label: Optional[str] = Field(default=None, max_length=128)


class SessionUpdateRequest(BaseModel):
    car_id: Optional[int] = None
    date: Optional[date_cls] = None
    start_soc: Optional[int] = Field(default=None, ge=0, le=100)
    end_soc: Optional[int] = Field(default=None, ge=0, le=100)
    kwh_added: Optional[float] = Field(default=None, gt=0, lt=1000)
    odometer_at_session_km: Optional[float] = Field(default=None, ge=0)
    charge_start_at: Optional[datetime] = None
    charge_end_at: Optional[datetime] = None
    location_id: Optional[int] = None
    charging_type: Optional[str] = Field(default=None, max_length=16)
    charging_mode: Optional[str] = Field(default=None, max_length=16)
    battery_care: Optional[bool] = None
    max_charge_current: Optional[str] = Field(default=None, max_length=16)
    # Editable so a user can correct a synthesis row that the cloud closed as
    # interrupted (e.g. a public DC charge whose start the cloud never saw).
    interrupted: Optional[bool] = None
    cost_per_kwh_override_p: Optional[float] = Field(default=None, ge=0)
    total_cost_pence_override: Optional[int] = Field(default=None, ge=0)
    charge_network: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = Field(default=None, max_length=512)
    user_label: Optional[str] = Field(default=None, max_length=128)


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _to_payload(
    cs: ChargingSession,
    *,
    location_name: Optional[str] = None,
    location_address: Optional[str] = None,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
    saved_vs_petrol_p: Optional[int] = None,
    comparison_basis: Optional[str] = None,
    breakeven_p_per_kwh: Optional[float] = None,
) -> SessionPayload:
    return SessionPayload(
        id=cs.id,
        user_id=cs.user_id,
        car_id=cs.car_id,
        plug_in_record_id=cs.plug_in_record_id,
        date=cs.date,
        charge_start_at=cs.charge_start_at,
        charge_end_at=cs.charge_end_at,
        start_soc=cs.start_soc,
        end_soc=cs.end_soc,
        kwh_added=cs.kwh_added,
        kwh_calculated=cs.kwh_calculated,
        odometer_at_session_km=cs.odometer_at_session_km,
        charging_type=cs.charging_type,
        charging_mode=cs.charging_mode,
        battery_care=cs.battery_care,
        max_charge_current=cs.max_charge_current,
        actual_charge_seconds=cs.actual_charge_seconds,
        interrupted=cs.interrupted,
        cost_pence=cs.cost_pence,
        cost_basis=cs.cost_basis,
        tariff_p_per_kwh=cs.tariff_p_per_kwh,
        cost_per_kwh_override_p=cs.cost_per_kwh_override_p,
        total_cost_pence_override=cs.total_cost_pence_override,
        location_id=cs.location_id,
        location_name=location_name,
        location_address=location_address,
        location_lat=location_lat,
        location_lng=location_lng,
        user_label=cs.user_label,
        charge_network=cs.charge_network,
        notes=cs.notes,
        source=cs.source,
        telematics_session_id=cs.telematics_session_id,
        power_curve=cs.power_curve,
        power_curve_approximate=bool(cs.power_curve) and cs.source != "synthesis",
        saved_vs_petrol_p=saved_vs_petrol_p,
        comparison_basis=comparison_basis,
        breakeven_p_per_kwh=breakeven_p_per_kwh,
    )


async def _get_owned(
    session: AsyncSession, session_id: int, user_id: int
) -> ChargingSession:
    result = await session.execute(
        select(ChargingSession).where(
            ChargingSession.id == session_id,
            ChargingSession.user_id == user_id,
        )
    )
    cs = result.scalar_one_or_none()
    if cs is None:
        raise HTTPException(status_code=404, detail="session not found")
    return cs


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


# Canonical session sources (see ChargingSession.source). 'cariad' is the
# deprecated legacy synthesis source — dropped from the filter allow-list as it
# is no longer offered in the UI; 'telegram'/'import' are the standalone-pivot
# ingest sources.
_VALID_SOURCES = frozenset({"manual", "synthesis", "telegram", "import"})
_VALID_SORTS = frozenset({"date", "cost", "energy", "saved"})
_VALID_DIRS = frozenset({"asc", "desc"})

# Maps the SQL-backed sort fields to their ChargingSession columns. `saved`
# is intentionally absent — it is computed in memory after the bulk pass.
_SORT_COLUMNS = {
    "date": ChargingSession.date,
    "cost": ChargingSession.cost_pence,
    "energy": ChargingSession.kwh_added,
}


@router.get("", response_model=list[SessionPayload])
async def list_sessions(
    request: Request,
    car_id: Optional[int] = Query(default=None),
    date_from: Optional[date_cls] = Query(default=None),
    date_to: Optional[date_cls] = Query(default=None),
    source: Optional[str] = Query(default=None),
    location_id: Optional[int] = Query(default=None),
    sort: str = Query(default="date"),
    dir: str = Query(default="desc"),
    session: AsyncSession = Depends(get_db),
) -> list[SessionPayload]:
    user_id = _user_id(request)
    if source is not None and source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"source must be one of {sorted(_VALID_SOURCES)}",
        )
    if sort not in _VALID_SORTS:
        raise HTTPException(
            status_code=400,
            detail=f"sort must be one of {sorted(_VALID_SORTS)}",
        )
    if dir not in _VALID_DIRS:
        raise HTTPException(
            status_code=400,
            detail=f"dir must be one of {sorted(_VALID_DIRS)}",
        )
    stmt = (
        select(
            ChargingSession,
            Location.name,
            Location.address,
            Location.centroid_lat,
            Location.centroid_lng,
        )
        .join(Location, ChargingSession.location_id == Location.id, isouter=True)
        .where(ChargingSession.user_id == user_id)
    )
    if car_id is not None:
        stmt = stmt.where(ChargingSession.car_id == car_id)
    if date_from is not None:
        stmt = stmt.where(ChargingSession.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(ChargingSession.date <= date_to)
    if source is not None:
        stmt = stmt.where(ChargingSession.source == source)
    if location_id is not None:
        stmt = stmt.where(ChargingSession.location_id == location_id)
    # `saved` is not a column — order by date for a stable base set, then
    # re-sort the computed value in memory below. For the SQL-backed fields
    # apply ORDER BY directly, keeping id as a stable tiebreaker.
    if sort == "saved":
        order_col = ChargingSession.date
        order_dir = "desc"
    else:
        order_col = _SORT_COLUMNS[sort]
        order_dir = dir
    if order_dir == "asc":
        stmt = stmt.order_by(order_col.asc(), ChargingSession.id.asc())
    else:
        stmt = stmt.order_by(order_col.desc(), ChargingSession.id.desc())

    result = await session.execute(stmt)
    rows = result.all()

    savings = await compute_savings_for_sessions(
        session, [cs for cs, *_ in rows]
    )

    payloads = []
    for cs, name, address, lat, lng in rows:
        saved_p, basis, breakeven = savings.get(cs.id, (None, None, None))
        payloads.append(
            _to_payload(
                cs,
                location_name=name,
                location_address=address,
                location_lat=lat,
                location_lng=lng,
                saved_vs_petrol_p=saved_p,
                comparison_basis=basis,
                breakeven_p_per_kwh=breakeven,
            )
        )

    if sort == "saved":
        # None sorts last in both directions; the boolean key puts rows with
        # a value ahead of those without, then the value orders within them.
        reverse = dir == "desc"
        payloads.sort(
            key=lambda p: (
                p.saved_vs_petrol_p is None,
                -(p.saved_vs_petrol_p or 0) if reverse else (p.saved_vs_petrol_p or 0),
            )
        )

    return payloads


async def _to_payload_with_location(
    session: AsyncSession, cs: ChargingSession
) -> SessionPayload:
    if cs.location_id is None:
        return _to_payload(cs)
    loc = await session.get(Location, cs.location_id)
    return _to_payload(
        cs,
        location_name=loc.name if loc else None,
        location_address=loc.address if loc else None,
        location_lat=loc.centroid_lat if loc else None,
        location_lng=loc.centroid_lng if loc else None,
    )


@router.post("", response_model=SessionPayload, status_code=201)
async def create_session(
    request: Request,
    body: SessionCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionPayload:
    user_id = _user_id(request)

    # Validate location ownership eagerly (also surfaces 400 before insert).
    await _get_owned_location(session, body.location_id, user_id)

    cs = ChargingSession(
        user_id=user_id,
        car_id=body.car_id,
        date=body.date,
        charge_start_at=body.charge_start_at,
        charge_end_at=body.charge_end_at,
        start_soc=body.start_soc,
        end_soc=body.end_soc,
        kwh_added=body.kwh_added,
        odometer_at_session_km=body.odometer_at_session_km,
        charging_type=body.charging_type,
        charging_mode=body.charging_mode,
        location_id=body.location_id,
        cost_per_kwh_override_p=body.cost_per_kwh_override_p,
        total_cost_pence_override=body.total_cost_pence_override,
        charge_network=body.charge_network,
        notes=body.notes,
        user_label=body.user_label,
        source="manual",
    )
    await _derive_kwh_calculated(session, cs)
    await apply_cost(session, cs)
    session.add(cs)
    await session.commit()
    await session.refresh(cs)
    return await _to_payload_with_location(session, cs)


@router.get("/{session_id}", response_model=SessionPayload)
async def get_session(
    session_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> SessionPayload:
    user_id = _user_id(request)
    cs = await _get_owned(session, session_id, user_id)
    payload = await _to_payload_with_location(session, cs)
    metrics = await compute_session_metrics(session, cs)
    # Pull the two new per-charge fields from metrics (added by the
    # backend-core agent alongside the per-charge savings model).
    # getattr with None default keeps this route compiling even when the
    # metrics dataclass is temporarily behind during parallel development.
    measured_miles = getattr(metrics, "measured_miles_since_previous", None)
    breakeven = getattr(metrics, "breakeven_p_per_kwh", None)
    payload.metrics = SessionMetricsPayload(
        miles_since_previous=metrics.miles_since_previous,
        measured_miles_since_previous=measured_miles,
        cost_per_mile_p=metrics.cost_per_mile_p,
        petrol_ppm=metrics.petrol_ppm,
        petrol_equivalent_cost_p=metrics.petrol_equivalent_cost_p,
        savings_vs_petrol_p=metrics.savings_vs_petrol_p,
        petrol_price_p_per_litre=metrics.petrol_price_p_per_litre,
        petrol_mpg=metrics.petrol_mpg,
        chain_session_ids=metrics.chain_session_ids,
        chain_total_cost_pence=metrics.chain_total_cost_pence,
        chain_anchor_id=metrics.chain_anchor_id,
        range_added_miles=metrics.range_added_miles,
        duration_minutes=metrics.duration_minutes,
        average_power_kw=metrics.average_power_kw,
        peak_power_kw=metrics.peak_power_kw,
        efficiency_percent=metrics.efficiency_percent,
        efficiency_mi_per_kwh=getattr(metrics, "efficiency_mi_per_kwh", None),
        efficiency_basis=getattr(metrics, "efficiency_basis", None),
    )
    # Mirror the per-charge savings + break-even onto the top-level payload
    # so list and detail shape are consistent.
    payload.saved_vs_petrol_p = metrics.savings_vs_petrol_p
    payload.comparison_basis = getattr(metrics, "comparison_basis", None)
    payload.breakeven_p_per_kwh = breakeven
    return payload


@router.put("/{session_id}", response_model=SessionPayload)
async def update_session(
    session_id: int,
    request: Request,
    body: SessionUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionPayload:
    user_id = _user_id(request)
    cs = await _get_owned(session, session_id, user_id)

    data = body.model_dump(exclude_unset=True)

    # Validate car ownership before any writes.  Active OR archived cars are
    # both allowed; do not filter on `active`.
    if "car_id" in data:
        target_car = await session.scalar(
            select(Car).where(Car.id == data["car_id"], Car.user_id == user_id)
        )
        if target_car is None:
            raise HTTPException(status_code=404, detail="Car not found")

    cost_dirty = bool(_COST_AFFECTING & data.keys())
    soc_dirty = bool(_SOC_AFFECTING & data.keys())
    override_changed = bool(_OVERRIDE_FIELDS & data.keys())
    for k, v in data.items():
        setattr(cs, k, v)

    if soc_dirty:
        await _derive_kwh_calculated(session, cs)
    if cost_dirty:
        await apply_cost(
            session, cs, first_compute=False, override_changed=override_changed
        )

    await session.commit()
    await session.refresh(cs)
    return await _to_payload_with_location(session, cs)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    user_id = _user_id(request)
    cs = await _get_owned(session, session_id, user_id)
    await session.delete(cs)
    await session.commit()
    return Response(status_code=204)
