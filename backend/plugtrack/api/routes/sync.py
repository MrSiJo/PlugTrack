"""Sync API: force-sync, status snapshot, SSE stream.

- POST /api/sync/{car_id}        — force a sync; returns job + stream_url
- GET  /api/sync/stream/{job_id} — SSE stream of events for that job
- GET  /api/sync/status          — orchestrator state snapshot

The wake-car feature has been removed entirely (POST /api/sync/{car_id}/wake
no longer exists). Wake calls drained the 12V battery without providing
faster data (Cupra's backend is push-based). See the 2026-05-30 quota-guard
spec for the full rationale.

All mutating routes are auth + CSRF gated by the global middleware. The
SSE GET is naturally CSRF-safe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ...services.event_bus import get_event_bus


router = APIRouter(prefix="/api/sync", tags=["sync"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _orchestrator(request: Request):
    orch = getattr(request.app.state, "sync_orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="sync orchestrator unavailable")
    return orch


@router.post("/{car_id}")
async def force_sync(car_id: int, request: Request) -> JSONResponse:
    _user_id(request)
    orch = _orchestrator(request)

    existing = orch.active_job(car_id)
    if existing is not None:
        return JSONResponse(
            status_code=202,
            content={
                "job_id": existing.job_id,
                "stream_url": f"/api/sync/stream/{existing.job_id}",
                "kind": existing.kind,
                "status": existing.status,
            },
        )

    # Fire-and-forget: kick off the sync, return the handle, let the
    # caller subscribe to the stream URL for the play-by-play.
    import asyncio

    job: list[Any] = []

    async def _runner():
        result = await orch.sync_car(car_id, kind="force")
        job.append(result)

    task = asyncio.create_task(_runner())

    # Wait briefly for the orchestrator to assign a job_id (single yield is
    # usually enough since sync_car constructs the job synchronously).
    for _ in range(20):
        if job:
            break
        await asyncio.sleep(0.005)

    if not job:
        # Worker is still spinning up but hasn't created the job yet —
        # poll the orchestrator for the active job_id.
        active = orch.active_job(car_id)
        if active is None:
            # Give it one more nudge; the task is at least scheduled.
            await asyncio.sleep(0.01)
            active = orch.active_job(car_id)
        if active is None:
            return JSONResponse(
                status_code=500,
                content={"detail": "failed to start sync"},
            )
        return JSONResponse(
            status_code=202,
            content={
                "job_id": active.job_id,
                "stream_url": f"/api/sync/stream/{active.job_id}",
                "kind": active.kind,
                "status": active.status,
            },
        )

    handle = job[0]
    # Don't await the task — let the orchestrator finish in the background.
    _ = task
    return JSONResponse(
        status_code=200,
        content={
            "job_id": handle.job_id,
            "stream_url": f"/api/sync/stream/{handle.job_id}",
            "kind": handle.kind,
            "status": handle.status,
        },
    )


@router.get("/stream/{job_id}")
async def stream_events(job_id: str, request: Request):
    _user_id(request)
    bus = get_event_bus()

    async def _events():
        async for evt in bus.subscribe(job_id):
            yield {
                "event": evt.event,
                "data": _json_dumps(evt.data),
            }

    return EventSourceResponse(_events())


@router.get("/status")
async def status(request: Request) -> JSONResponse:
    _user_id(request)
    orch = _orchestrator(request)
    snapshot = orch.snapshot()

    # Read today's quota usage from the DB and the budget from settings.
    requests_today = 0
    request_budget = 800
    quota_state_str = "ok"

    try:
        from ... import db as db_module
        from ...models.sync_quota import read_today_count
        from ...services.sync_scheduler import quota_factor, _quota_settings

        async with db_module.SessionLocal() as session:
            requests_today = await read_today_count(session)

        # Read the budget setting.
        from ...models import Setting
        from sqlalchemy import select as _select

        async with db_module.SessionLocal() as session:
            rows = (
                await session.execute(
                    _select(Setting).where(
                        Setting.key.in_(
                            ["sync_daily_request_budget", "sync_quota_soft_fraction"]
                        )
                    )
                )
            ).scalars().all()
        settings_map = {row.key: row.value for row in rows}
        budget, soft_fraction = _quota_settings(settings_map)
        request_budget = budget
        quota_state_str, _ = quota_factor(requests_today, budget, soft_fraction)
    except Exception:
        # Never let quota lookup break the status endpoint.
        pass

    return JSONResponse(content={
        "requests_today": requests_today,
        "request_budget": request_budget,
        "quota_state": quota_state_str,
        "cars": snapshot,
    })


def _json_dumps(data: dict) -> str:
    """Serialise event data to JSON, handling datetimes."""
    import json

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    return json.dumps(data, default=_default)
