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

import asyncio as _asyncio
import contextlib
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

_log = logging.getLogger(__name__)


_LOCK_HANDLE = None  # module-level so the lock survives lifespan scope


# ---------------------------------------------------------------------------
# Backup scheduler job — exported so tests can call it directly.
# ---------------------------------------------------------------------------

async def run_scheduled_backup(*, retention: int = 7) -> None:
    """Run one scheduled backup iteration: snapshot + prune.

    This is a module-level coroutine so tests can call it directly without
    real APScheduler timing.  The lifespan registers it as an interval job.

    Resilience: the entire body is wrapped in a broad try/except.  A backup
    failure (disk full, locked DB, …) is logged and swallowed — it MUST NOT
    crash the scheduler or the app.

    Note: the ``retention`` parameter is read INSIDE the job (passed in by
    the scheduler wrapper below) so that changes to the ``backup_retention``
    setting apply without a restart.  The *interval* is read once at startup;
    changing ``backup_interval_hours`` requires a restart (acceptable for v1).
    """
    from .services import backup as _bk

    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
        await _asyncio.to_thread(_bk.create_backup, timestamp)
        await _asyncio.to_thread(_bk.prune_backups, retention)
        _log.info("Scheduled backup completed (retention=%d).", retention)
    except Exception:  # noqa: BLE001
        _log.exception("Scheduled backup failed — swallowed to protect scheduler.")


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
        ("charging_session", "actual_charge_seconds", "INTEGER"),
        # screenshot_import usage columns (token/cost tracking)
        ("screenshot_import", "input_tokens", "INTEGER"),
        ("screenshot_import", "output_tokens", "INTEGER"),
        ("screenshot_import", "reasoning_tokens", "INTEGER"),
        # multi-car: friendly name (nullable, falls back to "{make} {model}")
        ("car", "name", "VARCHAR(64)"),
    )
    for table, column, ddl in additions:
        cols = (await conn.execute(_text(f"PRAGMA table_info({table})"))).all()
        existing = {row[1] for row in cols}
        if column not in existing:
            await conn.execute(
                _text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            )


async def reconcile_ai_enabled(session) -> None:
    """One-shot, idempotent: enable AI when an OpenAI key already exists.

    Post-pivot the live Telegram screenshot extraction depends on AI being
    on. Settings rows carry no provenance, so we use the literal default
    ("false") as the "untouched" sentinel: if a key exists and ai_enabled is
    still that default, flip it on. Never flips a user-chosen value.
    """
    from sqlalchemy import select
    from plugtrack.models.setting import Setting
    rows = (await session.execute(
        select(Setting).where(Setting.key.in_(["ai_enabled", "openai_api_key"]))
    )).scalars().all()
    by_key = {r.key: r for r in rows}
    ai = by_key.get("ai_enabled")
    key = by_key.get("openai_api_key")
    if ai is None or key is None:
        return
    has_key = bool(key.value)
    if has_key and ai.value in (None, "false"):
        ai.value = "true"
        await session.commit()


async def _read_bool_setting(session, key: str, default: bool) -> bool:
    """Read a bool setting value from the DB; fall back to `default`."""
    from sqlalchemy import select as _select
    from .models import Setting

    row = (await session.execute(_select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None or row.value is None:
        return default
    return str(row.value).strip().lower() in {"true", "1", "yes", "on"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _assert_single_worker()
    # Resolve via the module so test fixtures can monkeypatch
    # `plugtrack.db.engine` / `SessionLocal` after import.
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_additive_migrations(conn)
    async with db_module.SessionLocal() as session:
        await seed_defaults(session)
        await session.commit()
        await reconcile_ai_enabled(session)

    # Telegram screenshot-ingestion bot. The manager
    # owns the long-poll task and reconciles it against DB settings; it stays
    # off until `telegram_bot_enabled` is true (default off).
    from .services.telegram_manager import TelegramBotManager
    app.state.telegram_manager = TelegramBotManager(db_module.SessionLocal)
    await app.state.telegram_manager.reconcile()

    # MCP FastMCP session manager — must be started after the app is wired but
    # before requests are served.  The session manager is stored in
    # mcp_server._mcp_session_manager by build_mcp_app() (called at the bottom
    # of create_app()).  We start it here in the lifespan so it is running
    # during the `yield` that serves requests.  Uses an AsyncExitStack so we
    # can enter it unconditionally (even if None, we just skip it).
    from .mcp import server as _mcp_server_module
    _mcp_sm = getattr(_mcp_server_module, "_mcp_session_manager", None)
    _mcp_stack = contextlib.AsyncExitStack()
    if _mcp_sm is not None:
        await _mcp_stack.enter_async_context(_mcp_sm.run())
        _log.info("MCP session manager started.")

    # ---------------------------------------------------------------------------
    # Backup scheduler.
    # Starts whenever `backup_enabled` is true (default: true).
    # The interval is read once at startup; changing backup_interval_hours
    # requires a restart (acceptable for v1).  Retention is read fresh inside
    # each job invocation so changes apply without a restart.
    # ---------------------------------------------------------------------------
    from sqlalchemy import select as _select
    from .models import Setting as _Setting

    app.state.backup_scheduler = None
    async with db_module.SessionLocal() as _bk_session:
        backup_enabled = await _read_bool_setting(_bk_session, "backup_enabled", True)
        _bk_interval_hours = 24
        _bk_retention = 7
        if backup_enabled:
            _bk_interval_row = (await _bk_session.execute(
                _select(_Setting).where(_Setting.key == "backup_interval_hours")
            )).scalar_one_or_none()
            try:
                _bk_interval_hours = int(_bk_interval_row.value) if _bk_interval_row and _bk_interval_row.value else 24
            except (TypeError, ValueError):
                _bk_interval_hours = 24
            if _bk_interval_hours < 1:
                _log.warning(
                    "backup_interval_hours=%r is not positive; clamping to 24.",
                    _bk_interval_hours,
                )
                _bk_interval_hours = 24

            _bk_retention_row = (await _bk_session.execute(
                _select(_Setting).where(_Setting.key == "backup_retention")
            )).scalar_one_or_none()
            try:
                _bk_retention = int(_bk_retention_row.value) if _bk_retention_row and _bk_retention_row.value else 7
            except (TypeError, ValueError):
                _bk_retention = 7

    if backup_enabled:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler as _AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger as _IntervalTrigger

        _bk_retention_default = _bk_retention  # capture for closure fallback

        async def _backup_job() -> None:
            # Read retention fresh each run so setting changes apply without restart.
            retention = _bk_retention_default
            try:
                async with db_module.SessionLocal() as _s:
                    _ret_row = (await _s.execute(
                        _select(_Setting).where(_Setting.key == "backup_retention")
                    )).scalar_one_or_none()
                    if _ret_row and _ret_row.value:
                        try:
                            retention = int(_ret_row.value)
                        except (TypeError, ValueError):
                            pass
            except Exception:  # noqa: BLE001
                pass  # use captured default if DB read fails
            await run_scheduled_backup(retention=retention)

        try:
            _bk_scheduler = _AsyncIOScheduler()
            _bk_scheduler.add_job(
                _backup_job,
                trigger=_IntervalTrigger(hours=_bk_interval_hours),
                id="backup-scheduled",
                replace_existing=True,
                misfire_grace_time=300,
            )
            _bk_scheduler.start()
            app.state.backup_scheduler = _bk_scheduler
            _log.info(
                "Backup scheduler started: interval=%dh, retention=%d.",
                _bk_interval_hours,
                _bk_retention,
            )
        except Exception:  # noqa: BLE001
            _log.exception(
                "Backup scheduler failed to start — continuing without scheduled backups."
            )
            app.state.backup_scheduler = None

    try:
        yield
    finally:
        mgr = getattr(app.state, "telegram_manager", None)
        if mgr is not None:
            await mgr.stop()
        bk_scheduler = getattr(app.state, "backup_scheduler", None)
        if bk_scheduler is not None:
            try:
                bk_scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        # Stop the MCP session manager (if it was started)
        try:
            await _mcp_stack.aclose()
        except Exception:  # noqa: BLE001
            pass


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
    from .api.routes import geocode as geocode_routes
    from .api.routes import health as health_routes
    from .api.routes import insights as insights_routes
    from .api.routes import locations as locations_routes
    from .api.routes import maintenance as maintenance_routes
    from .api.routes import sessions as sessions_routes
    from .api.routes import settings as settings_routes
    from .api.routes import setup as setup_routes
    from .api.routes import telegram as telegram_routes
    from .api.routes import mcp_tokens as mcp_tokens_routes

    app.include_router(health_routes.router)
    app.include_router(setup_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(cars_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(locations_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(insights_routes.router)
    app.include_router(geocode_routes.router)
    app.include_router(charge_plan_routes.router)
    app.include_router(telegram_routes.router)
    app.include_router(maintenance_routes.router)
    app.include_router(mcp_tokens_routes.router)

    # MCP streamable-HTTP server — mounted at /mcp with its own bearer-token
    # auth middleware. The session-cookie auth + CSRF middlewares above exempt
    # /mcp (prefix match) because the MCP sub-app carries its own auth layer.
    #
    # build_mcp_app() registers tools and returns the wrapped ASGI app. It also
    # stores the FastMCP session_manager in mcp_server._mcp_session_manager so
    # the lifespan above can start/stop it.  The session_manager lifespan is
    # managed by passing it through the _McpAuthMiddleware lifespan scope, which
    # the Starlette inner app's lifespan handler handles natively.
    from .mcp.server import build_mcp_app
    mcp_asgi_app = build_mcp_app(db_module.SessionLocal)
    app.mount("/mcp", mcp_asgi_app)

    return app
