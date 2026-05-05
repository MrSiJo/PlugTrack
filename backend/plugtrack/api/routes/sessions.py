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
from ...models import ChargingSession, Location, Setting
from ...services.cost import compute_session_cost
from ...services.session_metrics import compute_session_metrics


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


class SessionMetricsPayload(BaseModel):
    miles_since_previous: Optional[float]
    cost_per_mile_p: Optional[float]
    petrol_ppm: Optional[float]
    petrol_equivalent_cost_p: Optional[int]
    savings_vs_petrol_p: Optional[int]
    petrol_price_p_per_litre: Optional[float]
    petrol_mpg: Optional[float]
    chain_session_ids: list[int] = []
    chain_total_cost_pence: Optional[int] = None
    chain_anchor_id: Optional[int] = None


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
    interrupted: bool
    cost_pence: Optional[int]
    cost_basis: str
    tariff_p_per_kwh: Optional[float]
    cost_per_kwh_override_p: Optional[float]
    total_cost_pence_override: Optional[int]
    location_id: Optional[int]
    location_name: Optional[str] = None
    location_address: Optional[str] = None
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
        interrupted=cs.interrupted,
        cost_pence=cs.cost_pence,
        cost_basis=cs.cost_basis,
        tariff_p_per_kwh=cs.tariff_p_per_kwh,
        cost_per_kwh_override_p=cs.cost_per_kwh_override_p,
        total_cost_pence_override=cs.total_cost_pence_override,
        location_id=cs.location_id,
        location_name=location_name,
        location_address=location_address,
        user_label=cs.user_label,
        charge_network=cs.charge_network,
        notes=cs.notes,
        source=cs.source,
        telematics_session_id=cs.telematics_session_id,
        power_curve=cs.power_curve,
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


async def _apply_cost(
    session: AsyncSession, cs: ChargingSession, user_id: int
) -> None:
    location = await _get_owned_location(session, cs.location_id, user_id)
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


@router.get("", response_model=list[SessionPayload])
async def list_sessions(
    request: Request,
    car_id: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[SessionPayload]:
    user_id = _user_id(request)
    stmt = (
        select(ChargingSession, Location.name, Location.address)
        .join(Location, ChargingSession.location_id == Location.id, isouter=True)
        .where(ChargingSession.user_id == user_id)
    )
    if car_id is not None:
        stmt = stmt.where(ChargingSession.car_id == car_id)
    stmt = stmt.order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
    result = await session.execute(stmt)
    return [
        _to_payload(cs, location_name=name, location_address=address)
        for cs, name, address in result.all()
    ]


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
    await _apply_cost(session, cs, user_id)
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
    payload.metrics = SessionMetricsPayload(
        miles_since_previous=metrics.miles_since_previous,
        cost_per_mile_p=metrics.cost_per_mile_p,
        petrol_ppm=metrics.petrol_ppm,
        petrol_equivalent_cost_p=metrics.petrol_equivalent_cost_p,
        savings_vs_petrol_p=metrics.savings_vs_petrol_p,
        petrol_price_p_per_litre=metrics.petrol_price_p_per_litre,
        petrol_mpg=metrics.petrol_mpg,
        chain_session_ids=metrics.chain_session_ids,
        chain_total_cost_pence=metrics.chain_total_cost_pence,
        chain_anchor_id=metrics.chain_anchor_id,
    )
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
    cost_dirty = bool(_COST_AFFECTING & data.keys())
    for k, v in data.items():
        setattr(cs, k, v)

    if cost_dirty:
        await _apply_cost(session, cs, user_id)

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
