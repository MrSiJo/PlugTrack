"""Tests for the backup scheduler job function (Task 5).

We test the job coroutine directly — no real APScheduler timing involved.
The test monkeypatches backup service helpers so no real DB is touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from plugtrack.services import backup as bk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(p: Path) -> None:
    """Create a minimal SQLite DB at *p* with a known row count."""
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE t(x)")
    conn.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(5)])
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: job creates a backup and applies pruning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_backup_creates_file_and_prunes(tmp_path, monkeypatch):
    """Calling the job function must create a backup and prune older ones."""
    import time as _time

    from plugtrack.main import run_scheduled_backup

    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    # Seed several pre-existing backups so pruning has something to delete.
    for i in range(3):
        bk.create_backup(f"2026-06-18T{i:02d}0000")
        _time.sleep(0.05)

    before_count = len(bk.list_backups())
    assert before_count == 3

    # Call the job directly.  retention=2 → only 2 newest survive after job adds 1.
    # Job creates 1 new file (4 total) then prunes to 2.
    await run_scheduled_backup(retention=2)

    remaining = bk.list_backups()
    # After pruning to 2, exactly 2 must survive.
    assert len(remaining) == 2
    # At least one backup file must exist (sanity).
    assert remaining[0]["size_bytes"] > 0


# ---------------------------------------------------------------------------
# Test 2: job swallows exceptions — a backup failure must not propagate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_backup_swallows_create_backup_exception(tmp_path, monkeypatch):
    """If create_backup raises, the job must log and swallow — never re-raise."""
    from plugtrack.main import run_scheduled_backup

    def _boom(timestamp: str) -> dict:
        raise OSError("disk full")

    monkeypatch.setattr(bk, "_source_db_path", lambda: tmp_path / "plugtrack.db")
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(bk, "create_backup", _boom)

    # Must NOT raise.
    await run_scheduled_backup(retention=7)


# ---------------------------------------------------------------------------
# Test 3: lifespan wires backup_scheduler into app.state when backup_enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_scheduler_present_in_app_state(app):
    """The lifespan must set app.state.backup_scheduler when backup_enabled=true."""
    async with app.router.lifespan_context(app):
        scheduler = getattr(app.state, "backup_scheduler", None)
        # The attribute must be set (not necessarily running in test environment
        # since the DB may not be a real file), but it must not be None.
        assert scheduler is not None


# ---------------------------------------------------------------------------
# Test 4: lifespan boots successfully when backup_interval_hours is "0"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_with_zero_backup_interval_does_not_raise(app, test_sessionmaker):
    """Lifespan must not raise when backup_interval_hours is set to "0".

    The clamp guard must convert the invalid "0" to 24, and the scheduler
    wiring try/except must ensure the app boots even if APScheduler raises.
    The key assertion is: the lifespan context enters without exception.
    """
    from plugtrack.models.setting import Setting
    from plugtrack.settings.seeds import seed_defaults
    from sqlalchemy import select as _select

    # Pre-seed the DB, then override backup_interval_hours to "0".
    async with test_sessionmaker() as session:
        await seed_defaults(session)
        await session.commit()
        row = (
            await session.execute(_select(Setting).where(Setting.key == "backup_interval_hours"))
        ).scalar_one_or_none()
        if row is not None:
            row.value = "0"
        else:
            session.add(Setting(key="backup_interval_hours", value="0"))
        await session.commit()

    # Enter the lifespan — must NOT raise.
    async with app.router.lifespan_context(app):
        # Scheduler should be present (clamped to 24h) or None (guard fired).
        # Either is acceptable; the critical assertion is no exception above.
        scheduler = getattr(app.state, "backup_scheduler", "MISSING")
        assert scheduler != "MISSING", "app.state.backup_scheduler must be set"
