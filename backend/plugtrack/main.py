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


async def run_digest_tick(
    *,
    now=None,
    sessionmaker=None,
    client_factory=None,
    _weekly_builder=None,
    _monthly_builder=None,
) -> None:
    """Run one digest-tick: send weekly/monthly digests if due and not already sent.

    Designed to be called on an hourly schedule (Task 4 registers it with
    APScheduler).  The whole body is wrapped in a broad try/except so a failure
    is logged + swallowed — it MUST NOT crash the scheduler.

    Parameters
    ----------
    now:
        The current instant in time (tz-aware recommended; if naive it is treated
        as already in Europe/London).  Defaults to ``datetime.now(LONDON)``.
    sessionmaker:
        Async-sessionmaker to use.  Defaults to ``db_module.SessionLocal``.
    client_factory:
        Callable ``token -> TelegramClient-like``.  Defaults to constructing a
        real ``TelegramClient(token)``.  Injected in tests to avoid network calls.
    _weekly_builder / _monthly_builder:
        Injectable digest builders (for testing).  Default to the real ones from
        ``services.digest``.
    """
    from zoneinfo import ZoneInfo as _ZoneInfo

    LONDON = _ZoneInfo("Europe/London")

    if now is None:
        from datetime import datetime as _datetime
        now = _datetime.now(LONDON)

    if sessionmaker is None:
        sessionmaker = db_module.SessionLocal

    if client_factory is None:
        from .services.telegram_client import TelegramClient as _TC
        client_factory = lambda token: _TC(token)  # noqa: E731

    if _weekly_builder is None:
        from .services.digest import build_weekly_digest as _bw
        _weekly_builder = _bw

    if _monthly_builder is None:
        from .services.digest import build_monthly_digest as _bm
        _monthly_builder = _bm

    try:
        from sqlalchemy import select as _select
        from .models import Setting as _Setting, User as _User

        async with sessionmaker() as session:
            # ── Load all relevant settings into a dict ────────────────────
            rows = {
                r.key: r.value
                for r in (await session.execute(_select(_Setting))).scalars().all()
            }

        def _truthy(v) -> bool:
            return (v or "").strip().lower() in {"true", "1", "yes", "on"}

        def _parse_ids(v) -> list[int]:
            return [int(x) for x in (v or "").replace(" ", "").split(",") if x]

        # ── Channel availability gate ─────────────────────────────────────
        if not _truthy(rows.get("telegram_bot_enabled")):
            _log.debug("run_digest_tick: bot disabled, skipping")
            return

        raw_token = rows.get("telegram_bot_token")
        if not raw_token:
            _log.debug("run_digest_tick: no telegram_bot_token, skipping")
            return

        allowed_ids = _parse_ids(rows.get("telegram_allowed_user_ids"))
        if not allowed_ids:
            _log.debug("run_digest_tick: no allowed_user_ids, skipping")
            return

        chat_id = allowed_ids[0]

        # Decrypt the token (may already be plain-text in tests if the value
        # isn't Fernet-encrypted; fall back gracefully).
        try:
            from .bootstrap import get_settings as _gs
            from .security.crypto import decrypt_secret as _ds
            token = _ds(raw_token, _gs().app_secret_key)
        except Exception:  # noqa: BLE001
            # In unit tests the token is seeded as plain text — use as-is.
            token = raw_token

        # ── Resolve the single app user ───────────────────────────────────
        async with sessionmaker() as session:
            user = (await session.execute(_select(_User))).scalar_one_or_none()
        if user is None:
            _log.warning("run_digest_tick: no user row, skipping")
            return
        user_id = user.id

        # ── Normalise now to London ───────────────────────────────────────
        now_local = now.astimezone(LONDON) if now.tzinfo is not None else now.replace(tzinfo=LONDON)

        # Parse send hour
        try:
            send_hour = int(rows.get("digest_send_hour") or "8")
        except (TypeError, ValueError):
            send_hour = 8

        # Current ISO week string: "YYYY-Www"
        iso = now_local.date().isocalendar()  # (year, week, weekday)
        current_iso_week = f"{iso[0]}-W{iso[1]:02d}"

        # Current month string: "YYYY-MM"
        current_month = now_local.strftime("%Y-%m")

        client = client_factory(token)

        # ── Delivery semantics (at-least-once) ───────────────────────────────
        # Send failure  → marker NOT advanced → tick retried next hourly run.
        #   A duplicate digest is possible if Telegram errors then recovers —
        #   this is acceptable for a low-frequency digest.
        # Empty period  → builder returns None → marker IS advanced immediately
        #   (no send, but no retry either — nothing to send).
        # The two periods are fully independent: a monthly failure must NOT
        # prevent the weekly marker from being committed, and vice-versa.
        # Each period runs inside its own try/except so neither can poison the
        # other; the outer try/except guards only the shared setup above.

        # ── WEEKLY ───────────────────────────────────────────────────────
        try:
            if _truthy(rows.get("digest_weekly_enabled")):
                # The anchor is: Monday of the current ISO week at send_hour.
                # It has passed when:
                #   - weekday > 0 (Tue–Sun, anchor was earlier this week), OR
                #   - weekday == 0 AND hour >= send_hour (Mon at or after send_hour)
                weekday = now_local.weekday()  # 0=Mon, 6=Sun
                weekly_anchor_passed = (weekday > 0) or (weekday == 0 and now_local.hour >= send_hour)

                last_weekly = rows.get("digest_last_weekly_sent") or ""

                if weekly_anchor_passed and last_weekly != current_iso_week:
                    async with sessionmaker() as session:
                        text = await _weekly_builder(session, user_id=user_id, now=now_local)

                    if text is not None:
                        # Failure here raises → marker NOT committed → retried next tick.
                        await client.send_message(chat_id=chat_id, text=text)

                    # Marker committed only after successful send (or empty period).
                    async with sessionmaker() as session:
                        marker_row = (await session.execute(
                            _select(_Setting).where(_Setting.key == "digest_last_weekly_sent")
                        )).scalar_one_or_none()
                        if marker_row is None:
                            session.add(_Setting(
                                key="digest_last_weekly_sent",
                                value=current_iso_week,
                                value_type="string",
                                group_name="telegram",
                                label="(internal) last weekly digest",
                                description="",
                                default_value=None,
                            ))
                        else:
                            marker_row.value = current_iso_week
                        await session.commit()
        except Exception:  # noqa: BLE001
            _log.exception("run_digest_tick: weekly period failed — swallowed; will retry next tick.")

        # ── MONTHLY ──────────────────────────────────────────────────────
        try:
            if _truthy(rows.get("digest_monthly_enabled")):
                # Anchor: 1st of current month at send_hour.
                # Passed when: day > 1, OR (day == 1 AND hour >= send_hour)
                monthly_anchor_passed = (now_local.day > 1) or (
                    now_local.day == 1 and now_local.hour >= send_hour
                )

                last_monthly = rows.get("digest_last_monthly_sent") or ""

                if monthly_anchor_passed and last_monthly != current_month:
                    async with sessionmaker() as session:
                        text = await _monthly_builder(session, user_id=user_id, now=now_local)

                    if text is not None:
                        # Failure here raises → marker NOT committed → retried next tick.
                        await client.send_message(chat_id=chat_id, text=text)

                    # Marker committed only after successful send (or empty period).
                    async with sessionmaker() as session:
                        marker_row = (await session.execute(
                            _select(_Setting).where(_Setting.key == "digest_last_monthly_sent")
                        )).scalar_one_or_none()
                        if marker_row is None:
                            session.add(_Setting(
                                key="digest_last_monthly_sent",
                                value=current_month,
                                value_type="string",
                                group_name="telegram",
                                label="(internal) last monthly digest",
                                description="",
                                default_value=None,
                            ))
                        else:
                            marker_row.value = current_month
                        await session.commit()
        except Exception:  # noqa: BLE001
            _log.exception("run_digest_tick: monthly period failed — swallowed; will retry next tick.")

    except Exception:  # noqa: BLE001
        _log.exception("run_digest_tick failed — swallowed to protect scheduler.")


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
        # smart-charge-planner: per-car charge capability fields
        ("car", "max_ac_kw", "FLOAT"),
        ("car", "max_dc_kw", "FLOAT"),
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

    # ---------------------------------------------------------------------------
    # Unified app-level scheduler.
    # One AsyncIOScheduler is always created so the digest-tick job runs
    # regardless of whether backups are enabled.  The backup job is added
    # conditionally inside the same scheduler when backup_enabled=true.
    # ---------------------------------------------------------------------------
    from apscheduler.schedulers.asyncio import AsyncIOScheduler as _AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger as _IntervalTrigger

    app.state.scheduler = None
    # Keep backward-compat alias so existing code / tests that check
    # app.state.backup_scheduler still work.
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

    try:
        _scheduler = _AsyncIOScheduler()

        # ── Digest tick (always) ─────────────────────────────────────────────
        async def _digest_job() -> None:
            await run_digest_tick()

        _scheduler.add_job(
            _digest_job,
            trigger=_IntervalTrigger(hours=1),
            id="digest-tick",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Backup job (conditional) ─────────────────────────────────────────
        if backup_enabled:
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

            _scheduler.add_job(
                _backup_job,
                trigger=_IntervalTrigger(hours=_bk_interval_hours),
                id="backup-scheduled",
                replace_existing=True,
                misfire_grace_time=300,
            )

        _scheduler.start()
        app.state.scheduler = _scheduler
        # Backward-compat: expose the backup scheduler under its old name too.
        if backup_enabled:
            app.state.backup_scheduler = _scheduler
        _log.info(
            "App scheduler started: digest-tick=1h%s.",
            f", backup-scheduled={_bk_interval_hours}h" if backup_enabled else "",
        )
    except Exception:  # noqa: BLE001
        _log.exception(
            "App scheduler failed to start — continuing without scheduled jobs."
        )
        app.state.scheduler = None
        app.state.backup_scheduler = None

    try:
        yield
    finally:
        mgr = getattr(app.state, "telegram_manager", None)
        if mgr is not None:
            await mgr.stop()
        _app_scheduler = getattr(app.state, "scheduler", None)
        if _app_scheduler is not None:
            try:
                _app_scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        # Stop the MCP session manager (if it was started)
        try:
            await _mcp_stack.aclose()
        except Exception:  # noqa: BLE001
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PlugTrack", version="3.8.0", lifespan=_lifespan)  # x-release-please-version

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
