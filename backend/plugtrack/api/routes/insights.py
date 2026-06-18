"""Insights routes — analytics aggregations.

GET /api/insights/by-location
    auth required; date_from/date_to optional (absent = all-time).
    Returns {rows, totals} — see services/insights.py.
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.insights import aggregate_by_location


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
