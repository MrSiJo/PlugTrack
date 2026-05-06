"""Dashboard summary route — single endpoint backing the v1 home page.

GET /api/dashboard
    auth required
    returns DashboardSummary (cars panels, recent sessions, lifetime
    totals, top locations) — see services/dashboard_service.py.

The orchestrator is read off `request.app.state.sync_orchestrator` so
test fixtures can inject a stub or omit it entirely.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.dashboard_service import dashboard_summary
from ...services.dashboard_trend import compute_spend_trend


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("")
async def get_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user_id = _user_id(request)
    orchestrator: Any | None = getattr(
        request.app.state, "sync_orchestrator", None
    )
    summary = await dashboard_summary(
        session, user_id=user_id, orchestrator=orchestrator
    )
    # `dashboard_summary` calls `mileage_tracking.get_status`, which may
    # materialise a rolled-over period (writes new rows). Commit so that
    # write is durable.
    await session.commit()
    return JSONResponse(content=_jsonify(summary.to_dict()))


@router.get("/spend-trend")
async def get_spend_trend(
    request: Request,
    days: int = 30,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=400, detail="days must be between 1 and 365"
        )
    user_id = _user_id(request)
    trend = await compute_spend_trend(session, user_id=user_id, days=days)
    return JSONResponse(
        content=[
            {"date": d.date.isoformat(), "cost_pence": d.cost_pence}
            for d in trend
        ]
    )


def _jsonify(value: Any) -> Any:
    """Coerce dataclass-derived dicts (with date/datetime) to JSON."""
    from datetime import date, datetime

    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
