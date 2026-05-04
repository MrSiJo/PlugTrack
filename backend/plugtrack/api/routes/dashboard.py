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
    return JSONResponse(content=_jsonify(summary.to_dict()))


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
