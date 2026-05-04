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


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    _assert_single_worker()
    # Resolve via the module so test fixtures can monkeypatch
    # `plugtrack.db.engine` / `SessionLocal` after import.
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db_module.SessionLocal() as session:
        await seed_defaults(session)
        await session.commit()
    yield


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
    from .api.routes import health as health_routes
    from .api.routes import settings as settings_routes
    from .api.routes import setup as setup_routes

    app.include_router(health_routes.router)
    app.include_router(setup_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(settings_routes.router)

    return app
