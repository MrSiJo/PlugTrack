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
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
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
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    result = await aggregate_by_location(
        session, user_id=user_id, date_from=date_from, date_to=date_to
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


@router.get("/overview")
async def get_overview(
    request: Request,
    date_from: Optional[date_cls] = Query(default=None),
    date_to: Optional[date_cls] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    lo, hi = await _effective_bounds(session, user_id, date_from, date_to)
    granularity = resolve_granularity(lo, hi) if lo is not None and hi is not None else "daily"

    over_time = await spend_energy_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to, granularity=granularity)
    split = await home_public_split(
        session, user_id=user_id, date_from=date_from, date_to=date_to)
    by_network = await network_breakdown(
        session, user_id=user_id, date_from=date_from, date_to=date_to)
    efficiency = await efficiency_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to, granularity=granularity)

    return JSONResponse(content={
        "granularity": granularity,
        "over_time": over_time,
        "split": split,
        "by_network": by_network,
        "efficiency": efficiency,
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
