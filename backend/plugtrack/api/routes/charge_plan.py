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

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car
from ...services.charge_planner import build_scenario_table, resolve_plan_inputs


router = APIRouter(prefix="/api/charge-plan", tags=["charge-plan"])


class ScenarioRowPayload(BaseModel):
    label: str
    power_kw: float
    minutes: int
    source_tag: str
    finish_at: Optional[str] = None
    nights: Optional[int] = None
    note: Optional[str] = None


class ScenarioPlanResponse(BaseModel):
    car_id: int
    start_soc: int
    target_soc: int
    battery_kwh: float
    loss_factor: float
    home_rate_p_per_kwh: float
    is_free: bool
    rows: list[ScenarioRowPayload]


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
    custom_kw: Optional[float] = Query(default=None, gt=0),
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
