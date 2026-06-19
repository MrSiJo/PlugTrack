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
