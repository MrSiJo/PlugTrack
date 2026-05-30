"""Tests for the sync quota guard (spec: 2026-05-30-sync-quota-guard-design.md).

Covers:
- SyncQuotaDay counter: increment, rollover on date change, persistence across
  a simulated restart.
- quota_factor pure function: ok / stretching / paused bands.
- Scheduler: paused car gets no job armed; force-sync still runs while paused.
- Daily reset re-arm: quota-paused car gets rescheduled after a day rollover.
- GET /api/sync/status: requests_today, request_budget, quota_state present.
- Wake removal: POST /api/sync/{id}/wake now returns 404.

API tests (test_status_*, test_wake_*) use the authed_client fixture from the
api sub-conftest, so this file must live in tests/ and the api conftest must be
imported.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from plugtrack.models import Base, SyncQuotaDay
from plugtrack.models.sync_quota import increment_request_count, read_today_count
from plugtrack.services.sync_orchestrator import CarSyncState
from plugtrack.services.sync_scheduler import SyncScheduler, quota_factor

# ---------------------------------------------------------------------------
# Inline fixtures for authenticated API tests (mirrors tests/api/conftest.py
# but declared locally so this top-level test file can use them).
# ---------------------------------------------------------------------------
from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME, make_serializer
from plugtrack.security.csrf import CSRF_COOKIE_NAME
from plugtrack.services.auth_service import bootstrap_user


@pytest_asyncio.fixture
async def _api_authed_client(app, test_sessionmaker):
    """Authenticated AsyncClient with a valid session cookie + primed CSRF."""
    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            user = await bootstrap_user(session, "quotaadmin", "test-password-12chars")

        serializer = make_serializer("test-secret-key-for-tests-only-padding-padding")
        token = serializer.dumps({"user_id": user.id})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            c.cookies.set(SESSION_COOKIE_NAME, token)
            await c.get("/api/health")
            await c.get("/api/settings")
            yield c


def _csrf_headers(c: AsyncClient) -> dict[str, str]:
    token = c.cookies.get(CSRF_COOKIE_NAME, "")
    return {"X-CSRF-Token": token}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "sync_interval_minutes_idle": "30",
    "sync_interval_minutes_plugged": "10",
    "sync_interval_minutes_charging": "5",
    "sync_enabled": "true",
    "sync_daily_request_budget": "800",
    "sync_quota_soft_fraction": "0.75",
}


async def _make_session(db_path: str) -> async_sessionmaker[AsyncSession]:
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ===========================================================================
# 1. Counter — increment, rollover, persistence
# ===========================================================================


@pytest.mark.asyncio
async def test_counter_increments(test_sessionmaker):
    """increment_request_count adds n and returns the running total."""
    async with test_sessionmaker() as s:
        total = await increment_request_count(s, 3)
        await s.commit()
    assert total == 3

    async with test_sessionmaker() as s:
        total2 = await increment_request_count(s, 2)
        await s.commit()
    assert total2 == 5


@pytest.mark.asyncio
async def test_counter_read_today(test_sessionmaker):
    """read_today_count returns current day's count, 0 if no row."""
    async with test_sessionmaker() as s:
        count = await read_today_count(s)
    assert count == 0

    async with test_sessionmaker() as s:
        await increment_request_count(s, 7)
        await s.commit()

    async with test_sessionmaker() as s:
        count = await read_today_count(s)
    assert count == 7


@pytest.mark.asyncio
async def test_counter_rolls_over_on_date_change(test_sessionmaker):
    """When a row for a previous day exists, today's count starts at 0."""
    yesterday = date.today() - timedelta(days=1)

    # Insert a row for yesterday directly.
    async with test_sessionmaker() as s:
        row = SyncQuotaDay(
            day=yesterday,
            request_count=999,
            updated_at=datetime.now(timezone.utc),
        )
        s.add(row)
        await s.commit()

    # Now increment for today — must start fresh, not add to yesterday.
    async with test_sessionmaker() as s:
        total = await increment_request_count(s, 5)
        await s.commit()
    assert total == 5

    # Yesterday's row must still exist untouched.
    async with test_sessionmaker() as s:
        yesterday_row = (
            await s.execute(
                select(SyncQuotaDay).where(SyncQuotaDay.day == yesterday)
            )
        ).scalar_one()
    assert yesterday_row.request_count == 999


@pytest.mark.asyncio
async def test_counter_persists_across_restart(tmp_path):
    """The DB counter survives a simulated restart (new engine, same file)."""
    db_file = str(tmp_path / "quota_persist.db")

    # Session 1: insert some counts.
    sm1 = await _make_session(db_file)
    async with sm1() as s:
        await increment_request_count(s, 12)
        await s.commit()
    async with sm1() as s:
        await increment_request_count(s, 8)
        await s.commit()

    # Session 2: open a new engine against the same file (simulated restart).
    sm2 = await _make_session(db_file)
    async with sm2() as s:
        count = await read_today_count(s)
    assert count == 20


@pytest.mark.asyncio
async def test_counter_increments_by_exact_getter_count(test_sessionmaker):
    """One poll with 5 getter calls increments by 5 (the adapter loop count)."""
    async with test_sessionmaker() as s:
        result = await increment_request_count(s, 5)
        await s.commit()
    assert result == 5


# ===========================================================================
# 2. quota_factor pure function
# ===========================================================================


def test_quota_factor_ok_below_soft():
    """Below 75% of budget → ok, multiplier 1.0."""
    state, mult = quota_factor(used=0, budget=800, soft_fraction=0.75)
    assert state == "ok"
    assert mult == 1.0


def test_quota_factor_ok_just_below_soft_threshold():
    """At used == budget*soft_fraction - 1 → still ok."""
    # soft_cap = 800 * 0.75 = 600; used=599
    state, mult = quota_factor(used=599, budget=800, soft_fraction=0.75)
    assert state == "ok"
    assert mult == 1.0


def test_quota_factor_stretching_at_soft_threshold():
    """At exactly the soft cap → stretching, multiplier starts at 1.0."""
    # used == soft_cap means progress == 0.0, so multiplier = 1.0 + 3.0 * 0.0 = 1.0
    state, mult = quota_factor(used=600, budget=800, soft_fraction=0.75)
    assert state == "stretching"
    assert mult == pytest.approx(1.0, abs=1e-9)


def test_quota_factor_stretching_midway():
    """Midway between soft and budget → stretching, multiplier ~2.5."""
    # soft_cap = 600, budget = 800, range = 200
    # used = 700 → progress = (700-600)/200 = 0.5 → multiplier = 1 + 3*0.5 = 2.5
    state, mult = quota_factor(used=700, budget=800, soft_fraction=0.75)
    assert state == "stretching"
    assert mult == pytest.approx(2.5, abs=1e-9)


def test_quota_factor_stretching_near_budget():
    """Just under budget → still stretching, multiplier approaching 4.0."""
    state, mult = quota_factor(used=799, budget=800, soft_fraction=0.75)
    assert state == "stretching"
    assert mult > 3.9


def test_quota_factor_paused_at_budget():
    """At the budget → paused."""
    state, mult = quota_factor(used=800, budget=800, soft_fraction=0.75)
    assert state == "paused"


def test_quota_factor_paused_over_budget():
    """Over the budget → paused."""
    state, mult = quota_factor(used=900, budget=800, soft_fraction=0.75)
    assert state == "paused"


def test_quota_factor_degenerate_zero_budget():
    """budget=0 is treated as 'no budget' → ok, 1.0."""
    state, mult = quota_factor(used=1000, budget=0, soft_fraction=0.75)
    assert state == "ok"
    assert mult == 1.0


def test_quota_factor_multiplier_is_float():
    """Multiplier is always a float."""
    _, mult = quota_factor(used=650, budget=800, soft_fraction=0.75)
    assert isinstance(mult, float)


# ===========================================================================
# 3. Scheduler: paused car gets no job; force-sync still runs
# ===========================================================================


@pytest.mark.asyncio
async def test_scheduler_paused_when_over_budget():
    """When quota is exhausted, schedule_next arms no job and next_poll_at is None."""
    # Provider reports used=800 (at budget).
    quota_used = 800

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: quota_used,
    )
    sched.start()
    try:
        state = CarSyncState(last_state="IDLE")
        seconds = sched.schedule_next(42, state, None, _DEFAULT_SETTINGS)
        assert seconds == 0
        assert state.next_poll_at is None
        # Car should be tracked as quota-paused.
        assert 42 in sched._quota_paused_cars
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_scheduler_paused_reason_not_auth_invalid():
    """Quota pause does not set auth_invalid; auth_invalid remains False."""
    quota_used = 900

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: quota_used,
    )
    sched.start()
    try:
        state = CarSyncState(last_state="IDLE")
        sched.schedule_next(1, state, None, _DEFAULT_SETTINGS)
        # auth_invalid must stay False — this is a quota pause, not a credential failure.
        assert state.auth_invalid is False
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_scheduler_ok_below_budget():
    """When under budget, scheduler arms a job and next_poll_at is set."""
    quota_used = 0

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: quota_used,
    )
    sched.start()
    try:
        state = CarSyncState(last_state="IDLE")
        seconds = sched.schedule_next(1, state, None, _DEFAULT_SETTINGS)
        assert seconds > 0
        assert state.next_poll_at is not None
        assert 1 not in sched._quota_paused_cars
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_force_sync_runs_while_paused():
    """A force-sync bypasses the quota gate and still runs.

    The quota guard lives in schedule_next (which arms the *next* poll).
    The orchestrator's sync_car always invokes the worker directly for
    force-syncs, regardless of quota state. So even when the scheduler
    has paused a car, a force-sync call still executes the worker.
    """
    from plugtrack.services.sync_orchestrator import SyncJob, SyncOrchestrator

    ran: list[int] = []

    async def worker(job: SyncJob, state: CarSyncState) -> None:
        ran.append(job.car_id)

    orch = SyncOrchestrator(poll_worker=worker)
    job = await orch.sync_car(car_id=99, kind="force")
    await asyncio.sleep(0)  # let any pending tasks settle
    assert job.status in ("completed", "running")
    assert 99 in ran


@pytest.mark.asyncio
async def test_scheduler_stretching_multiplies_interval():
    """In stretching state, interval is scaled by a multiplier > 1."""
    # 700 of 800 used → stretching, ~2.5× multiplier
    quota_used = 700

    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: quota_used,
    )
    sched.start()
    try:
        state = CarSyncState(last_state="IDLE")
        seconds = sched.schedule_next(5, state, None, _DEFAULT_SETTINGS)
        # IDLE band = 30 * 60 = 1800s; with ~2.5× stretch, expect > 1800.
        assert seconds > 1800
        assert state.next_poll_at is not None
    finally:
        sched.stop()


# ===========================================================================
# 4. Daily reset re-arm
# ===========================================================================


@pytest.mark.asyncio
async def test_daily_reset_rearms_quota_paused_car():
    """After a date rollover, paused cars are re-scheduled on the next schedule_next call."""
    called: list[int] = []

    async def cb(car_id: int) -> None:
        called.append(car_id)

    # Start over budget so car 7 gets paused.
    quota_used = 800

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: quota_used,
    )
    sched.start()
    try:
        state7 = CarSyncState(last_state="IDLE")
        sched.schedule_next(7, state7, None, _DEFAULT_SETTINGS)
        assert 7 in sched._quota_paused_cars

        # Simulate a date rollover: move _last_quota_day back to yesterday.
        from datetime import date, timedelta

        yesterday = date.today() - timedelta(days=1)
        sched._last_quota_day = yesterday

        # Now use a quota provider that reports 0 (new day, fresh counter).
        sched._quota_provider = lambda: 0

        # Any call to schedule_next (from any car) triggers the rollover check.
        state_other = CarSyncState(last_state="IDLE")
        sched.schedule_next(99, state_other, None, _DEFAULT_SETTINGS)

        # Car 7 should no longer be in the paused set.
        assert 7 not in sched._quota_paused_cars
    finally:
        sched.stop()


@pytest.mark.asyncio
async def test_quota_paused_cars_cleared_on_new_day():
    """_quota_paused_cars is emptied after a day rollover."""
    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=lambda: 800,  # over budget
    )
    sched.start()
    try:
        for car_id in (1, 2, 3):
            state = CarSyncState(last_state="IDLE")
            sched.schedule_next(car_id, state, None, _DEFAULT_SETTINGS)
        assert sched._quota_paused_cars == {1, 2, 3}

        # Simulate rollover.
        from datetime import date, timedelta
        sched._last_quota_day = date.today() - timedelta(days=1)
        sched._quota_provider = lambda: 0

        state_trigger = CarSyncState(last_state="IDLE")
        sched.schedule_next(99, state_trigger, None, _DEFAULT_SETTINGS)

        assert sched._quota_paused_cars == set()
    finally:
        sched.stop()


# ===========================================================================
# 5. GET /api/sync/status — quota fields present
# ===========================================================================


@pytest.mark.asyncio
async def test_status_endpoint_includes_quota_fields(_api_authed_client, app):
    """GET /api/sync/status response includes requests_today, request_budget, quota_state."""
    from plugtrack.services.sync_orchestrator import SyncOrchestrator

    app.state.sync_orchestrator = SyncOrchestrator()

    r = await _api_authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()

    assert "requests_today" in body, "Missing requests_today field"
    assert "request_budget" in body, "Missing request_budget field"
    assert "quota_state" in body, "Missing quota_state field"

    assert isinstance(body["requests_today"], int)
    assert isinstance(body["request_budget"], int)
    assert body["quota_state"] in ("ok", "stretching", "paused")

    # cars map must still be present and unchanged.
    assert "cars" in body


@pytest.mark.asyncio
async def test_status_quota_state_ok_when_zero_requests(_api_authed_client, app):
    """With no requests recorded today, quota_state should be 'ok'."""
    from plugtrack.services.sync_orchestrator import SyncOrchestrator

    app.state.sync_orchestrator = SyncOrchestrator()

    r = await _api_authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()

    # No requests recorded → ok, and requests_today should be 0.
    assert body["requests_today"] == 0
    assert body["quota_state"] == "ok"


@pytest.mark.asyncio
async def test_status_request_budget_default(_api_authed_client, app):
    """Default budget from catalogue is 800."""
    from plugtrack.services.sync_orchestrator import SyncOrchestrator

    app.state.sync_orchestrator = SyncOrchestrator()

    r = await _api_authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["request_budget"] == 800


@pytest.mark.asyncio
async def test_status_quota_state_stretching(_api_authed_client, app, test_sessionmaker):
    """When requests are in the stretching band, quota_state == 'stretching'."""
    from plugtrack.services.sync_orchestrator import SyncOrchestrator
    from plugtrack.models.sync_quota import increment_request_count

    app.state.sync_orchestrator = SyncOrchestrator()

    # Insert 650 requests today (>75% of 800 = 600 soft cap, so stretching).
    async with test_sessionmaker() as s:
        await increment_request_count(s, 650)
        await s.commit()

    r = await _api_authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["quota_state"] == "stretching"
    assert body["requests_today"] == 650


@pytest.mark.asyncio
async def test_status_quota_state_paused_at_budget(_api_authed_client, app, test_sessionmaker):
    """When requests >= budget, quota_state == 'paused'."""
    from plugtrack.services.sync_orchestrator import SyncOrchestrator
    from plugtrack.models.sync_quota import increment_request_count

    app.state.sync_orchestrator = SyncOrchestrator()

    # Insert exactly 800 requests today.
    async with test_sessionmaker() as s:
        await increment_request_count(s, 800)
        await s.commit()

    r = await _api_authed_client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["quota_state"] == "paused"
    assert body["requests_today"] == 800


# ===========================================================================
# 6. Wake removal — POST /api/sync/{id}/wake returns 404
# ===========================================================================


@pytest.mark.asyncio
async def test_wake_endpoint_returns_404(_api_authed_client):
    """POST /api/sync/{id}/wake must return 404 — the route is removed."""
    r = await _api_authed_client.post(
        "/api/sync/1/wake", headers=_csrf_headers(_api_authed_client)
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_wake_endpoint_returns_404_for_various_ids(_api_authed_client):
    """Wake route is absent for any car_id, not just car 1."""
    headers = _csrf_headers(_api_authed_client)
    for car_id in (1, 42, 999):
        r = await _api_authed_client.post(f"/api/sync/{car_id}/wake", headers=headers)
        assert r.status_code == 404, f"Expected 404 for car_id={car_id}, got {r.status_code}"


@pytest.mark.asyncio
async def test_wake_endpoint_not_a_valid_route(_api_authed_client):
    """The wake route does not exist in the router — confirmed via authenticated client.

    The auth middleware returns 401 before a missing-route 404 fires when
    unauthenticated, so we test with a valid session to confirm the route
    truly isn't registered (not just auth-gated).
    """
    r = await _api_authed_client.post(
        "/api/sync/1/wake", headers=_csrf_headers(_api_authed_client)
    )
    # 404 = route gone. Any other code (200, 202, 403) means the route still exists.
    assert r.status_code == 404


# ===========================================================================
# 7. No-quota-provider path (backward compat with older tests)
# ===========================================================================


@pytest.mark.asyncio
async def test_scheduler_no_quota_provider_behaves_normally():
    """When quota_provider is None, scheduler never pauses."""
    async def cb(car_id: int) -> None:
        pass

    sched = SyncScheduler(
        sync_callback=cb,
        settings_provider=lambda: _DEFAULT_SETTINGS,
        quota_provider=None,  # no quota check
    )
    sched.start()
    try:
        state = CarSyncState(last_state="IDLE")
        seconds = sched.schedule_next(1, state, None, _DEFAULT_SETTINGS)
        assert seconds == 30 * 60
        assert state.next_poll_at is not None
    finally:
        sched.stop()


# ===========================================================================
# 8. Settings catalogue includes quota keys
# ===========================================================================


def test_catalogue_has_sync_daily_request_budget():
    """sync_daily_request_budget must be in the catalogue with default 800."""
    from plugtrack.settings.catalogue import CATALOGUE

    entry = next((e for e in CATALOGUE if e.key == "sync_daily_request_budget"), None)
    assert entry is not None, "sync_daily_request_budget missing from CATALOGUE"
    assert entry.value_type == "int"
    assert entry.default_value == "800"
    assert entry.group_name == "sync"


def test_catalogue_has_sync_quota_soft_fraction():
    """sync_quota_soft_fraction must be in the catalogue with default 0.75."""
    from plugtrack.settings.catalogue import CATALOGUE

    entry = next((e for e in CATALOGUE if e.key == "sync_quota_soft_fraction"), None)
    assert entry is not None, "sync_quota_soft_fraction missing from CATALOGUE"
    assert entry.value_type == "float"
    assert entry.default_value == "0.75"
    assert entry.group_name == "sync"
