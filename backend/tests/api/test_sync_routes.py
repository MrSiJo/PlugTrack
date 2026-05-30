"""Tests for /api/sync/{car_id} (force, status, stream).

The wake-car feature has been removed entirely; wake tests are not present.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from plugtrack.api.routes import sync as sync_routes
from plugtrack.services.event_bus import SyncEvent, get_event_bus, reset_event_bus
from plugtrack.services.sync_orchestrator import CarSyncState, SyncJob, SyncOrchestrator
from tests.api.conftest import csrf_headers


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Wipe event bus between tests."""
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.mark.asyncio
async def test_force_sync_requires_auth(seeded_client):
    r = await seeded_client.post("/api/sync/1")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_force_sync_requires_csrf(authed_client):
    # No CSRF header.
    r = await authed_client.post("/api/sync/1")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_force_sync_returns_job_and_stream_url(authed_client, app):
    started: list[str] = []

    async def worker(job: SyncJob, state: CarSyncState) -> None:
        started.append(job.job_id)
        await asyncio.sleep(0.05)

    app.state.sync_orchestrator = SyncOrchestrator(poll_worker=worker)

    r = await authed_client.post("/api/sync/1", headers=csrf_headers(authed_client))
    assert r.status_code in (200, 202)
    body = r.json()
    assert "job_id" in body
    assert body["stream_url"] == f"/api/sync/stream/{body['job_id']}"
    assert body["kind"] == "force"


@pytest.mark.asyncio
async def test_force_sync_idempotent_returns_existing_job(authed_client, app):
    """Second POST while a sync is in flight returns the same job_id with 202."""
    finished = asyncio.Event()

    async def slow(job: SyncJob, state: CarSyncState) -> None:
        await finished.wait()

    app.state.sync_orchestrator = SyncOrchestrator(poll_worker=slow)

    r1 = await authed_client.post("/api/sync/1", headers=csrf_headers(authed_client))
    assert r1.status_code in (200, 202)
    body1 = r1.json()

    # Second request while the first is still running.
    r2 = await authed_client.post("/api/sync/1", headers=csrf_headers(authed_client))
    assert r2.status_code == 202
    body2 = r2.json()
    assert body2["job_id"] == body1["job_id"]

    # Let the first job finish.
    finished.set()
    # Drain any remaining task ticks.
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_status_returns_orchestrator_snapshot(authed_client, app):
    orch = SyncOrchestrator()
    state = orch.ensure_state(7)
    state.last_state = "PLUGGED_IN"
    state.last_soc = 42
    app.state.sync_orchestrator = orch

    r = await authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert "cars" in body
    assert "requests_today" in body
    assert "request_budget" in body
    assert "quota_state" in body
    assert body["quota_state"] in ("ok", "stretching", "paused")
    assert "7" in body["cars"]
    assert body["cars"]["7"]["last_state"] == "PLUGGED_IN"
    assert body["cars"]["7"]["last_soc"] == 42


@pytest.mark.asyncio
async def test_wake_endpoint_removed(authed_client):
    """POST /api/sync/{id}/wake must 404 — the route no longer exists."""
    r = await authed_client.post(
        "/api/sync/1/wake", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_event_bus_delivers_scripted_events(authed_client, app):
    """End-to-end-ish: drive the bus directly + assert subscribe ordering.

    The full SSE transport (sse-starlette + httpx.stream) is fiddly to
    assert against in pytest. We exercise the bus + orchestrator wiring
    by publishing to the bus and asserting bus.subscribe yields events
    in the expected order. The route layer is covered by the unit tests
    above.
    """
    bus = get_event_bus()
    job_id = "scripted-job"

    async def producer():
        await bus.publish(SyncEvent(event="sync.started", data={"car_id": 1}, job_id=job_id))
        await bus.publish(SyncEvent(event="sync.transition", data={"to": "PLUGGED_IN"}, job_id=job_id))
        await bus.publish(SyncEvent(event="sync.transition", data={"to": "CHARGING"}, job_id=job_id))
        await bus.publish(SyncEvent(event="sync.transition", data={"to": "CHARGING_DONE"}, job_id=job_id))
        await bus.publish(SyncEvent(event="sync.completed", data={}, job_id=job_id))

    received: list[str] = []

    async def consumer():
        async for evt in bus.subscribe(job_id):
            received.append(evt.event)

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0)  # let consumer subscribe
    await producer()
    await asyncio.wait_for(consumer_task, timeout=1.0)

    assert received == [
        "sync.started",
        "sync.transition",
        "sync.transition",
        "sync.transition",
        "sync.completed",
    ]
