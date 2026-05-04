"""Sync API: force-sync, wake-car, status snapshot, SSE stream.

- POST /api/sync/{car_id}        — force a sync; returns job + stream_url
- GET  /api/sync/stream/{job_id} — SSE stream of events for that job
- POST /api/sync/{car_id}/wake   — push a wake-up via pycupra setRefresh,
                                   rate-limited 1×/30min/car
- GET  /api/sync/status          — orchestrator state snapshot

All mutating routes are auth + CSRF gated by the global middleware. The
SSE GET is naturally CSRF-safe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ...services.event_bus import get_event_bus


router = APIRouter(prefix="/api/sync", tags=["sync"])


WAKE_COOLDOWN_SECONDS = 30 * 60  # 1 wake per 30 minutes per car (12V protection)

# Module-level state (single-worker assumption; documented tripwire in main.py).
_last_wake_at: dict[int, datetime] = {}


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


def _wake_provider(request: Request):
    """Optional adapter callable for waking the car.

    Tests inject a mock via app.state.wake_provider. Production wires the
    pycupra adapter in main.py lifespan.
    """
    return getattr(request.app.state, "wake_provider", None)


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


@router.post("/{car_id}/wake")
async def wake_car(car_id: int, request: Request) -> JSONResponse:
    _user_id(request)
    now = _utcnow()
    last = _last_wake_at.get(car_id)
    if last is not None:
        delta = (now - last).total_seconds()
        if delta < WAKE_COOLDOWN_SECONDS:
            retry_after = int(WAKE_COOLDOWN_SECONDS - delta) + 1
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "wake rate-limited; try again later",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    provider = _wake_provider(request)
    if provider is None:
        # No provider wired (e.g. in tests). Mark the wake attempt so the
        # rate-limit ratchets, return 200 with skipped:true.
        _last_wake_at[car_id] = now
        return JSONResponse(
            status_code=200,
            content={"woken": False, "reason": "no_provider", "car_id": car_id},
        )

    try:
        woken = await provider(car_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": "wake failed", "error": str(exc)},
        )

    _last_wake_at[car_id] = now
    return JSONResponse(
        status_code=200,
        content={"woken": bool(woken), "car_id": car_id},
    )


@router.get("/status")
async def status(request: Request) -> JSONResponse:
    _user_id(request)
    orch = _orchestrator(request)
    snapshot = orch.snapshot()
    return JSONResponse(content={"cars": snapshot})


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


def reset_wake_cooldowns() -> None:
    """Test helper — clear the in-memory rate-limit dict."""
    _last_wake_at.clear()
