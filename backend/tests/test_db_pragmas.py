"""PLUG-L1 (partial): the engine applies per-connection SQLite PRAGMAs.

`busy_timeout` avoids instant "database is locked" errors; it is
per-connection, so it's issued from a connect-event listener
(`plugtrack.db.set_sqlite_pragmas`) which the test engine shares.

`foreign_keys=ON` is deliberately not enabled — see the docstring on
`set_sqlite_pragmas` for the two production blockers found.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_sqlite_busy_timeout_is_applied(test_sessionmaker):
    async with test_sessionmaker() as s:
        assert (await s.execute(text("PRAGMA busy_timeout"))).scalar_one() == 5000
