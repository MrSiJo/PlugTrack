"""Insights routes — analytics aggregations.

GET /api/insights/by-location
    auth required; date_from/date_to optional (absent = all-time).
    Returns {rows, totals} — see services/insights.py.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car
from ...services.insights import aggregate_by_location
from ...services.insights_stats import (
    efficiency_over_time,
    home_public_split,
    mileage_allowance_view,
    network_breakdown,
    resolve_granularity,
    spend_energy_over_time,
    window_totals,
)
from ...services.ownership_trends import (
    battery_health_summary,
    capacity_trend as _capacity_trend,
    efficiency_by_month,
    seasonal_delta,
)


router = APIRouter(prefix="/api/insights", tags=["insights"])


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("/by-location")
async def get_by_location(
    request: Request,
    date_from: Optional[date_cls] = Query(default=None),
    date_to: Optional[date_cls] = Query(default=None),
    car_id: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    result = await aggregate_by_location(
        session, user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id
    )
    return JSONResponse(
        content={
            "rows": [
                {
                    "location_id": r.location_id,
                    "name": r.name,
                    "is_home": r.is_home,
                    "is_free": r.is_free,
                    "spend_pence": r.spend_pence,
                    "kwh": r.kwh,
                    "sessions": r.sessions,
                    "avg_p_per_kwh": r.avg_p_per_kwh,
                    "first_at": r.first_at,
                    "last_at": r.last_at,
                    "pct_of_spend": r.pct_of_spend,
                }
                for r in result.rows
            ],
            "totals": result.totals,
        }
    )


async def _effective_bounds(session, user_id, date_from, date_to):
    """Resolve concrete (lo, hi) for granularity. Missing bounds fall back
    to the user's min/max session date. Returns (None, None) if no data."""
    from sqlalchemy import func, select
    from ...models import ChargingSession
    lo, hi = date_from, date_to
    if lo is None:
        lo = (await session.execute(
            select(func.min(ChargingSession.date)).where(
                ChargingSession.user_id == user_id))).scalar_one_or_none()
    if hi is None:
        hi = (await session.execute(
            select(func.max(ChargingSession.date)).where(
                ChargingSession.user_id == user_id))).scalar_one_or_none()
    return lo, hi


async def _resolve_trend_car(
    session: AsyncSession, *, user_id: int, car_id: Optional[int]
) -> Optional[Car]:
    """Return the Car to use for ownership-trend aggregations.

    When car_id is provided, load that specific car (no active filter — it
    could be an archived car if the caller asks for it).  When car_id is
    None, resolve to the user's first ACTIVE car ordered by id; trends are
    inherently per-car and we need a single battery_kwh to anchor them.
    Returns None if no suitable car can be found.
    """
    if car_id is not None:
        stmt = select(Car).where(Car.user_id == user_id, Car.id == car_id)
    else:
        stmt = (
            select(Car)
            .where(Car.user_id == user_id, Car.active == True)  # noqa: E712
            .order_by(Car.id)
            .limit(1)
        )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("/overview")
async def get_overview(
    request: Request,
    date_from: Optional[date_cls] = Query(default=None),
    date_to: Optional[date_cls] = Query(default=None),
    car_id: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    lo, hi = await _effective_bounds(session, user_id, date_from, date_to)
    granularity = resolve_granularity(lo, hi) if lo is not None and hi is not None else "daily"

    over_time = await spend_energy_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to, granularity=granularity,
        car_id=car_id)
    split = await home_public_split(
        session, user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id)
    by_network = await network_breakdown(
        session, user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id)
    efficiency = await efficiency_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to, granularity=granularity,
        car_id=car_id)

    # Ownership-trend keys — inherently per-car; resolve the car to use.
    trend_car = await _resolve_trend_car(session, user_id=user_id, car_id=car_id)
    if trend_car is not None:
        seasonal_efficiency = await efficiency_by_month(
            session,
            user_id=user_id,
            car_id=trend_car.id,
            battery_kwh=trend_car.battery_kwh,
        )
        capacity_trend_data = await _capacity_trend(
            session,
            user_id=user_id,
            car_id=trend_car.id,
            battery_kwh=trend_car.battery_kwh,
        )
        battery_health = await battery_health_summary(
            session,
            user_id=user_id,
            car_id=trend_car.id,
            battery_kwh=trend_car.battery_kwh,
        )
    else:
        seasonal_efficiency = []
        capacity_trend_data = []
        battery_health = None

    return JSONResponse(content={
        "granularity": granularity,
        "over_time": over_time,
        "split": split,
        "by_network": by_network,
        "efficiency": efficiency,
        "seasonal_efficiency": seasonal_efficiency,
        "capacity_trend": capacity_trend_data,
        "seasonal_delta": seasonal_delta(seasonal_efficiency),
        "battery_health": battery_health,
    })


@router.get("/mileage")
async def get_mileage(
    request: Request,
    car_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    view = await mileage_allowance_view(
        session, user_id=user_id, car_id=car_id, today=datetime.now(timezone.utc).date())
    return JSONResponse(content=view)
