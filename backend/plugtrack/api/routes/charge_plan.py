"""GET /api/charge-plan — scenario-table charge planning endpoint.

Auth + CSRF enforced by existing middleware (normal authed GET).
All queries filter by request.state.user_id.

Contract:
    GET /api/charge-plan?car_id=<int>&start_soc=<int>&target_soc=<int>[&custom_kw=<float>]
    200 JSON per ScenarioPlanResponse:
        {car_id, start_soc, target_soc, battery_kwh, loss_factor,
         home_rate_p_per_kwh, is_free,
         rows: [{label, power_kw, minutes, source_tag, finish_at?, nights?, note?}]}
    Errors:
        404 — car not found or not owned by authenticated user.
        400 — target_soc <= start_soc, or derived power/battery invalid.
        422 — FastAPI query validation (soc out of 0-100 range).

Note: archived (active=False) cars are plannable — no active filter is applied.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car
from ...services.charge_planner import (
    build_blended_plan,
    build_scenario_table,
    resolve_plan_inputs,
)

router = APIRouter(prefix="/api/charge-plan", tags=["charge-plan"])

# Fallback rapid-DC rate (p/kWh) when the caller supplies none. The user
# overrides this on the planner form; it is only a sensible public default.
_DEFAULT_PUBLIC_DC_RATE_P = 45.0


class ScenarioRowPayload(BaseModel):
    label: str
    power_kw: float
    minutes: int
    source_tag: str
    finish_at: str | None = None
    nights: int | None = None
    note: str | None = None


class ScenarioPlanResponse(BaseModel):
    car_id: int
    start_soc: int
    target_soc: int
    battery_kwh: float
    loss_factor: float
    home_rate_p_per_kwh: float
    is_free: bool
    rows: list[ScenarioRowPayload]


class BlendedPhasePayload(BaseModel):
    kwh: float
    minutes: int
    cost_pence: int


class BlendedTotalPayload(BaseModel):
    kwh: float
    minutes: int
    cost_pence: int
    cost_per_mile_p: float | None = None
    mi_per_kwh: float | None = None


class BlendedPlanResponse(BaseModel):
    car_id: int
    start_soc: int
    dc_stop_soc: int
    target_soc: int
    battery_kwh: float
    loss_factor: float
    dc_rate_p: float
    home_rate_p_per_kwh: float
    is_free: bool
    dc_phase: BlendedPhasePayload
    home_phase: BlendedPhasePayload
    total: BlendedTotalPayload


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("", response_model=ScenarioPlanResponse)
async def get_charge_plan(
    request: Request,
    car_id: int = Query(...),
    start_soc: int = Query(..., ge=0, le=100),
    target_soc: int = Query(..., ge=0, le=100),
    custom_kw: float | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_db),
) -> ScenarioPlanResponse:
    user_id = _user_id(request)

    # Validate SoC range.
    if target_soc <= start_soc:
        raise HTTPException(
            status_code=400,
            detail="target_soc must be greater than start_soc",
        )

    # Fetch car — must exist and belong to the authenticated user.
    # No active filter: archived cars are still plannable.
    result = await session.execute(select(Car).where(Car.id == car_id, Car.user_id == user_id))
    car = result.scalar_one_or_none()
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")

    # Validate battery capacity.
    if car.battery_kwh is None or car.battery_kwh <= 0:
        raise HTTPException(
            status_code=400,
            detail="car battery_kwh is missing or not positive",
        )

    # Resolve DB-backed inputs (settings, home location, recent sessions, DC capability).
    try:
        inputs = await resolve_plan_inputs(session, car, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build scenario table.
    rows = build_scenario_table(
        start_soc=start_soc,
        target_soc=target_soc,
        battery_kwh=inputs.battery_kwh,
        loss_factor=inputs.loss_factor,
        ac={
            "home_actual_kw": inputs.power_kw,
            "ac_ceiling_kw": inputs.ac_ceiling_kw,
            "window_minutes": inputs.window_minutes,
            "window_start_str": inputs.window_start_str,
            "home_rate_p_per_kwh": inputs.home_rate_p_per_kwh,
            "is_free": inputs.is_free,
        },
        dc={
            "capability": inputs.dc_capability,
            "ceiling": inputs.dc_ceiling,
        },
        custom_kw=custom_kw,
    )

    return ScenarioPlanResponse(
        car_id=car_id,
        start_soc=start_soc,
        target_soc=target_soc,
        battery_kwh=inputs.battery_kwh,
        loss_factor=inputs.loss_factor,
        home_rate_p_per_kwh=inputs.home_rate_p_per_kwh,
        is_free=inputs.is_free,
        rows=[
            ScenarioRowPayload(
                label=row.label,
                power_kw=row.power_kw,
                minutes=row.minutes,
                source_tag=row.source_tag,
                finish_at=row.finish_at,
                nights=row.nights,
                note=row.note,
            )
            for row in rows
        ],
    )


@router.get("/blended", response_model=BlendedPlanResponse)
async def get_blended_charge_plan(
    request: Request,
    car_id: int = Query(...),
    start_soc: int = Query(..., ge=0, le=100),
    dc_stop_soc: int = Query(..., ge=0, le=100),
    home_target_soc: int = Query(..., ge=0, le=100),
    dc_rate_p: float | None = Query(default=None, ge=0),
    dc_charger_cap_kw: float | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_db),
) -> BlendedPlanResponse:
    """Two-phase blended plan: rapid DC to ``dc_stop_soc`` then home AC to ``home_target_soc``."""
    user_id = _user_id(request)

    # SoC ordering: start <= dc_stop <= target, and at least some charging.
    if not (start_soc <= dc_stop_soc <= home_target_soc):
        raise HTTPException(
            status_code=400,
            detail="require start_soc <= dc_stop_soc <= home_target_soc",
        )
    if home_target_soc <= start_soc:
        raise HTTPException(
            status_code=400,
            detail="home_target_soc must be greater than start_soc",
        )

    # Fetch car — must exist and belong to the authenticated user.
    result = await session.execute(select(Car).where(Car.id == car_id, Car.user_id == user_id))
    car = result.scalar_one_or_none()
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")

    if car.battery_kwh is None or car.battery_kwh <= 0:
        raise HTTPException(
            status_code=400,
            detail="car battery_kwh is missing or not positive",
        )

    try:
        inputs = await resolve_plan_inputs(session, car, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Resolve DC rate + charger cap. The cap can never exceed the car's DC ceiling.
    rate = dc_rate_p if dc_rate_p is not None else _DEFAULT_PUBLIC_DC_RATE_P
    if dc_charger_cap_kw is not None:
        effective_cap = min(dc_charger_cap_kw, inputs.dc_ceiling)
    else:
        effective_cap = inputs.dc_ceiling

    mi_per_kwh = (
        float(car.nominal_efficiency_mi_per_kwh) if car.nominal_efficiency_mi_per_kwh else None
    )

    plan = build_blended_plan(
        start_soc=start_soc,
        dc_stop_soc=dc_stop_soc,
        target_soc=home_target_soc,
        battery_kwh=inputs.battery_kwh,
        dc_capability=inputs.dc_capability,
        dc_rate_p=rate,
        dc_charger_cap_kw=effective_cap,
        home_power_kw=inputs.power_kw,
        home_window={
            "window_minutes": inputs.window_minutes,
            "window_start_str": inputs.window_start_str,
        },
        home_rate_p=inputs.home_rate_p_per_kwh,
        is_free=inputs.is_free,
        loss_factor=inputs.loss_factor,
        mi_per_kwh=mi_per_kwh,
    )

    return BlendedPlanResponse(
        car_id=car_id,
        start_soc=start_soc,
        dc_stop_soc=dc_stop_soc,
        target_soc=home_target_soc,
        battery_kwh=inputs.battery_kwh,
        loss_factor=inputs.loss_factor,
        dc_rate_p=rate,
        home_rate_p_per_kwh=inputs.home_rate_p_per_kwh,
        is_free=inputs.is_free,
        dc_phase=BlendedPhasePayload(
            kwh=plan.dc_phase.kwh,
            minutes=plan.dc_phase.minutes,
            cost_pence=plan.dc_phase.cost_pence,
        ),
        home_phase=BlendedPhasePayload(
            kwh=plan.home_phase.kwh,
            minutes=plan.home_phase.minutes,
            cost_pence=plan.home_phase.cost_pence,
        ),
        total=BlendedTotalPayload(
            kwh=plan.total.kwh,
            minutes=plan.total.minutes,
            cost_pence=plan.total.cost_pence,
            cost_per_mile_p=plan.total.cost_per_mile_p,
            mi_per_kwh=plan.total.mi_per_kwh,
        ),
    )
