"""FastAPI app factory + lifespan.

`create_app()` is the single entry point for both production and tests.
The lifespan handler:

1. Asserts single-worker exclusivity. SQLite + APScheduler in-process
   scheduler are not multi-process safe, so we refuse to start a second
   worker. We use both an env-var check (WEB_CONCURRENCY) and a
   filesystem lock (so direct `--workers N` invocations also fail).
2. Runs `Base.metadata.create_all` to ensure the schema exists in dev.
3. Calls `seed_defaults` to insert any catalogue rows missing from the
   `setting` table.
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import db as db_module
from .api.auth_middleware import AuthMiddleware
from .api.rate_limit import limiter
from .bootstrap import get_settings
from .models import Base
from .security.csrf import CsrfMiddleware
from .settings.seeds import seed_defaults


_LOCK_HANDLE = None  # module-level so the lock survives lifespan scope


def _assert_single_worker() -> None:
    """Two-layer multi-worker tripwire.

    1. Reject if WEB_CONCURRENCY is set to anything other than "1".
    2. Acquire an exclusive filesystem lock so `uvicorn --workers N` /
       `gunicorn -w N` (which fork without setting WEB_CONCURRENCY) also
       fail — only the first worker gets the lock.

    The lock is released when the process exits.
    """
    web_concurrency = os.getenv("WEB_CONCURRENCY")
    if web_concurrency is not None and web_concurrency != "1":
        raise RuntimeError(
            "PlugTrack must run with WEB_CONCURRENCY=1. SQLite + the in-process "
            "APScheduler are not safe across multiple workers. "
            f"Got WEB_CONCURRENCY={web_concurrency!r}."
        )

    # Skip the file lock during pytest — fixtures repeatedly create_app()
    # within the same process and would self-deadlock.
    if "pytest" in sys.modules:
        return

    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        return  # already locked in this process

    lock_path = Path(tempfile.gettempdir()) / "plugtrack.lock"
    handle = open(lock_path, "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        handle.close()
        raise RuntimeError(
            f"Another PlugTrack worker already holds {lock_path}. "
            "Run with a single worker only."
        ) from exc
    _LOCK_HANDLE = handle


async def _apply_additive_migrations(conn) -> None:
    """Add columns introduced after the initial schema.

    SQLAlchemy's `create_all` only creates missing tables — it does NOT
    add columns to existing tables. We don't run Alembic; instead we run
    a tiny set of idempotent `ALTER TABLE ... ADD COLUMN` statements
    here. Each entry is `(table, column, ddl_fragment)`. The check is
    "does this column already exist?" via PRAGMA, so re-runs are no-ops.
    """
    from sqlalchemy import text as _text

    additions = (
        ("location", "default_charge_network", "VARCHAR(64)"),
        ("charging_session", "battery_care", "BOOLEAN"),
        ("charging_session", "max_charge_current", "VARCHAR(16)"),
        ("car_state", "last_battery_care", "BOOLEAN"),
        ("car_state", "last_max_charge_current", "VARCHAR(16)"),
        ("car_state", "last_charging_estimated_end_at", "DATETIME"),
        ("car_state", "last_odometer_km", "INTEGER"),
    )
    for table, column, ddl in additions:
        cols = (await conn.execute(_text(f"PRAGMA table_info({table})"))).all()
        existing = {row[1] for row in cols}
        if column not in existing:
            await conn.execute(
                _text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            )


async def _apply_value_migrations(conn) -> None:
    """Idempotent value-level data migrations.

    Unlike `_apply_additive_migrations` (which adds columns), this
    function corrects stored values after renames. Each migration is
    expressed as a conditional UPDATE so re-runs are cheap no-ops (the
    WHERE clause finds nothing on subsequent runs).
    """
    from sqlalchemy import text as _text

    # Rename: source='phantom' -> source='unconfirmed'.
    # The 'phantom' name was used during initial development; the stored
    # value was renamed to 'unconfirmed' in the first public release.
    # Safe to re-run: rows already updated have source='unconfirmed' so
    # the WHERE clause matches nothing on subsequent startups.
    await conn.execute(
        _text(
            "UPDATE charging_session SET source='unconfirmed' WHERE source='phantom'"
        )
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _assert_single_worker()
    # Resolve via the module so test fixtures can monkeypatch
    # `plugtrack.db.engine` / `SessionLocal` after import.
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_additive_migrations(conn)
        await _apply_value_migrations(conn)
    async with db_module.SessionLocal() as session:
        await seed_defaults(session)
        await session.commit()

    # Phase 4: orchestrator + scheduler + event bus.
    from .services.event_bus import get_event_bus
    from .services.sync_orchestrator import SyncOrchestrator
    from .services.sync_scheduler import SyncScheduler
    from .services.sync_worker import (
        get_user_sync_settings,
        make_pycupra_adapter_provider,
        make_settings_provider,
        make_worker,
        _quota_cache,
    )

    # Seed the in-memory quota cache from the DB so the scheduler knows
    # the current day's count immediately after a restart (before the first
    # poll). Without this, a restart resets the cache to 0 and the scheduler
    # would ignore accumulated quota until the next poll fires.
    from .models.sync_quota import read_today_count as _read_today_count
    async with db_module.SessionLocal() as _quota_seed_session:
        _today_count = await _read_today_count(_quota_seed_session)
        _quota_cache.seed(_today_count)

    bus = get_event_bus()
    app.state.event_bus = bus
    # Phase 4.6: wire the production poll worker (StateMachine + DB
    # writes + cost + clustering + event emission).
    poll_worker = make_worker(
        db_sessionmaker=db_module.SessionLocal,
        settings_provider=make_settings_provider(db_module.SessionLocal),
        adapter_provider=make_pycupra_adapter_provider(db_module.SessionLocal),
        bus=bus,
    )
    app.state.sync_orchestrator = SyncOrchestrator(poll_worker=poll_worker)

    # Rehydrate per-car state from the persisted snapshots so the
    # dashboard shows last-known battery/range/state immediately on
    # cold start (before the first periodic sync fires).
    from sqlalchemy import select as _select
    from .models import CarStateSnapshot, PlugInRecord
    rehydrated_car_ids: list[int] = []
    async with db_module.SessionLocal() as session:
        snaps = (
            await session.execute(_select(CarStateSnapshot))
        ).scalars().all()
        for snap in snaps:
            st = app.state.sync_orchestrator.ensure_state(snap.car_id)
            st.last_state = snap.last_state or "IDLE"
            st.last_soc = snap.last_soc
            st.last_odometer_km = snap.last_odometer_km
            st.last_target_soc = snap.last_target_soc
            st.last_electric_range_km = snap.last_electric_range_km
            st.last_charging_power_kw = snap.last_charging_power_kw
            st.last_battery_care = snap.last_battery_care
            st.last_max_charge_current = snap.last_max_charge_current
            st.last_charging_estimated_end_at = snap.last_charging_estimated_end_at
            st.last_position_lat = snap.last_position_lat
            st.last_position_lng = snap.last_position_lng
            st.last_location_id = snap.last_location_id
            st.last_car_captured_timestamp = snap.last_car_captured_timestamp
            rehydrated_car_ids.append(snap.car_id)

            # Orphan-plug-in watchdog: if the snapshot says we're IDLE,
            # any open PlugInRecord for this car is the leftover of an
            # unplug missed across a restart. Close it conservatively at
            # the snapshot's last-known timestamp + SoC so the row stops
            # haunting subsequent state transitions.
            if st.last_state == "IDLE":
                orphans = (
                    await session.execute(
                        _select(PlugInRecord).where(
                            PlugInRecord.car_id == snap.car_id,
                            PlugInRecord.plug_out_at.is_(None),
                        )
                    )
                ).scalars().all()
                for pir in orphans:
                    pir.plug_out_at = snap.last_car_captured_timestamp
                    pir.plug_out_soc = snap.last_soc
        await session.commit()

    async def _scheduled_sync(car_id: int) -> None:
        await app.state.sync_orchestrator.sync_car(car_id, kind="periodic")

    def _settings_provider() -> dict:
        # Synchronous read used by SyncScheduler.start()/schedule_next.
        # We block on a fresh session — startup is short-lived; per-tick
        # reads also pay this cost but APScheduler's loop tolerates it.
        import asyncio as _asyncio

        async def _read() -> dict:
            async with db_module.SessionLocal() as session:
                # user_id is unused inside; we pass 0 deliberately.
                return await get_user_sync_settings(session, 0)

        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                # Defensive: should only be hit if called during the
                # active loop. APScheduler uses the same loop and will
                # await `_scheduled_sync` rather than calling this; this
                # branch is the fallback for tests.
                return {}
        except RuntimeError:
            pass
        return _asyncio.run(_read())

    from .services.sync_worker import get_today_request_count as _quota_provider

    app.state.sync_scheduler = SyncScheduler(
        sync_callback=_scheduled_sync,
        settings_provider=_settings_provider,
        quota_provider=_quota_provider,
    )
    app.state.sync_scheduler.start()

    # After every sync (force or periodic) the scheduler arms the next
    # periodic poll based on the observed state.
    def _after_sync(car_id: int, state) -> None:  # type: ignore[no-untyped-def]
        try:
            app.state.sync_scheduler.schedule_next(
                car_id=car_id,
                state=state,
                telemetry=None,
                settings=_settings_provider(),
            )
        except Exception:  # noqa: BLE001
            pass

    app.state.sync_orchestrator.set_on_complete(_after_sync)

    # Arm a periodic poll for every car we just rehydrated. Without this
    # the scheduler stays idle until the user clicks Force sync, which
    # leaves "Next sync: never" on the dashboard after every restart.
    if app.state.sync_scheduler.is_enabled():
        _bootstrap_settings = _settings_provider()
        for car_id in rehydrated_car_ids:
            state = app.state.sync_orchestrator.ensure_state(car_id)
            try:
                app.state.sync_scheduler.schedule_next(
                    car_id=car_id,
                    state=state,
                    telemetry=None,
                    settings=_bootstrap_settings,
                )
            except Exception:  # noqa: BLE001
                pass

    try:
        yield
    finally:
        app.state.sync_scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PlugTrack", version="2.0.0", lifespan=_lifespan)

    # Slowapi wiring.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Order matters: outermost (added last) runs first. We want auth to
    # gate first, then CSRF.
    app.add_middleware(CsrfMiddleware, cookie_secure=settings.cookie_secure)
    app.add_middleware(AuthMiddleware, secret_key=settings.app_secret_key)

    # Routers — registered here so `app.routes` exposes everything to
    # the security-invariants test.
    from .api.routes import auth as auth_routes
    from .api.routes import cars as cars_routes
    from .api.routes import charge_plan as charge_plan_routes
    from .api.routes import dashboard as dashboard_routes
    from .api.routes import health as health_routes
    from .api.routes import locations as locations_routes
    from .api.routes import sessions as sessions_routes
    from .api.routes import settings as settings_routes
    from .api.routes import setup as setup_routes
    from .api.routes import sync as sync_routes

    app.include_router(health_routes.router)
    app.include_router(setup_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(cars_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(locations_routes.router)
    app.include_router(sync_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(charge_plan_routes.router)

    return app
