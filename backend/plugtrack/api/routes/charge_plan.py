"""GET /api/charge-plan — home charge planning endpoint.

Auth + CSRF enforced by existing middleware (normal authed GET).
All queries filter by request.state.user_id.

Contract (frozen):
    GET /api/charge-plan?car_id=<int>&start_soc=<int>&target_soc=<int>
    200 JSON per the charge plan shape defined in services/charge_planner.py.
    Errors:
        404 — car not found or not owned by authenticated user.
        400 — target_soc <= start_soc, or derived power/battery invalid.
        422 — FastAPI query validation (soc out of 0-100 range).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car
from ...services.charge_planner import compute_charge_plan, resolve_plan_inputs


router = APIRouter(prefix="/api/charge-plan", tags=["charge-plan"])


class NightPayload(BaseModel):
    index: int
    minutes: int
    end_soc: int
    finish_at: str


class ChargePlanResponse(BaseModel):
    car_id: int
    start_soc: int
    target_soc: int
    battery_kwh: float
    kwh_needed: float
    power_kw: float
    power_basis: str
    sample_size: int
    total_minutes: int
    window_start: str
    window_end: str
    window_minutes: int
    fits_one_window: bool
    nights: list[NightPayload]
    nights_needed: int
    finish_at: str
    cost_pence: int
    home_rate_p_per_kwh: float
    is_free: bool


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("", response_model=ChargePlanResponse)
async def get_charge_plan(
    request: Request,
    car_id: int = Query(...),
    start_soc: int = Query(..., ge=0, le=100),
    target_soc: int = Query(..., ge=0, le=100),
    session: AsyncSession = Depends(get_db),
) -> ChargePlanResponse:
    user_id = _user_id(request)

    # Validate SoC range.
    if target_soc <= start_soc:
        raise HTTPException(
            status_code=400,
            detail="target_soc must be greater than start_soc",
        )

    # Fetch car — must exist and belong to the authenticated user.
    result = await session.execute(
        select(Car).where(Car.id == car_id, Car.user_id == user_id)
    )
    car = result.scalar_one_or_none()
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")

    # Validate battery capacity.
    if car.battery_kwh is None or car.battery_kwh <= 0:
        raise HTTPException(
            status_code=400,
            detail="car battery_kwh is missing or not positive",
        )

    # Resolve DB-backed inputs (settings, home location, recent sessions).
    try:
        inputs = await resolve_plan_inputs(session, car, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if inputs.power_kw <= 0:
        raise HTTPException(
            status_code=400,
            detail="resolved charging power is 0 or negative",
        )

    # Pure computation.
    plan = compute_charge_plan(
        start_soc=start_soc,
        target_soc=target_soc,
        battery_kwh=inputs.battery_kwh,
        power_kw=inputs.power_kw,
        window_minutes=inputs.window_minutes,
        window_start_str=inputs.window_start_str,
        home_rate_p_per_kwh=inputs.home_rate_p_per_kwh,
        is_free=inputs.is_free,
    )

    return ChargePlanResponse(
        car_id=car_id,
        start_soc=start_soc,
        target_soc=target_soc,
        battery_kwh=inputs.battery_kwh,
        kwh_needed=plan.kwh_needed,
        power_kw=inputs.power_kw,
        power_basis=inputs.power_basis,
        sample_size=inputs.sample_size,
        total_minutes=plan.total_minutes,
        window_start=inputs.window_start_str,
        window_end=inputs.window_end_str,
        window_minutes=inputs.window_minutes,
        fits_one_window=plan.fits_one_window,
        nights=[
            NightPayload(
                index=n.index,
                minutes=n.minutes,
                end_soc=n.end_soc,
                finish_at=n.finish_at,
            )
            for n in plan.nights
        ],
        nights_needed=plan.nights_needed,
        finish_at=plan.finish_at,
        cost_pence=plan.cost_pence,
        home_rate_p_per_kwh=inputs.home_rate_p_per_kwh,
        is_free=inputs.is_free,
    )
