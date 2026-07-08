"""Async SQLAlchemy engine + session factory.

Module-level `engine` and `SessionLocal` are intentionally importable so
test fixtures can monkeypatch them per-test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .bootstrap import get_settings


def set_sqlite_pragmas(sync_engine: Engine) -> None:
    """Register a connect-event listener applying per-connection PRAGMAs.

    PLUG-L1 (partial): `busy_timeout` avoids instant "database is locked"
    errors when a write briefly overlaps another connection's transaction.
    It is per-connection, so it must be issued on every new DBAPI
    connection.

    `PRAGMA foreign_keys=ON` was deliberately NOT enabled: turning it on
    revealed that (a) `delete_session` leaves dangling
    `screenshot_import.created_session_id` references, and (b) legacy
    `plug_in_record` rows in a pre-3.0 production DB would block location
    delete/merge. Enforcing FKs needs those paths fixed (and a data
    cleanup) first — app-level ownership checks compensate meanwhile.

    Exported so the test fixtures (which build their own engines) can apply
    the same PRAGMAs production gets.
    """

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


_settings = get_settings()
engine = create_async_engine(_settings.database_url, future=True)
set_sqlite_pragmas(engine.sync_engine)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession."""
    async with SessionLocal() as session:
        yield session
