"""Tests for the backup snapshot service (Task 2).

Uses tmp_path + monkeypatch to redirect _source_db_path() and _data_dir()
to a temporary SQLite file so no real DB is touched.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from plugtrack.services import backup as bk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(p: Path) -> None:
    """Create a minimal SQLite DB at *p* with 5 rows in table t."""
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE t(x)")
    conn.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(5)])
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------

def test_create_backup_is_valid_copy(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    info = bk.create_backup("2026-06-19T000000")

    # File exists and is a valid SQLite DB with the same row count.
    copy = sqlite3.connect(info["path"])
    count = copy.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    copy.close()
    assert count == 5
    assert info["size_bytes"] > 0
    assert info["name"] == "plugtrack-2026-06-19T000000.db"
    # Backup must live inside backups_dir (data_dir / "backups")
    assert Path(info["path"]).parent == tmp_path / "backups"


def test_create_backup_creates_backups_dir(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    backups = tmp_path / "backups"
    assert not backups.exists()

    bk.create_backup("2026-06-19T120000")
    assert backups.is_dir()


# ---------------------------------------------------------------------------
# list_backups
# ---------------------------------------------------------------------------

def test_list_backups_sorted_newest_first(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    # Create three backups with small sleeps to ensure distinct mtimes.
    ts1 = "2026-06-19T010000"
    ts2 = "2026-06-19T020000"
    ts3 = "2026-06-19T030000"
    for ts in (ts1, ts2, ts3):
        bk.create_backup(ts)
        time.sleep(0.05)  # ensure filesystem mtime differs

    items = bk.list_backups()
    assert len(items) == 3

    # Newest first: last-written file has the highest mtime.
    names = [i["name"] for i in items]
    assert names[0] == f"plugtrack-{ts3}.db"
    assert names[-1] == f"plugtrack-{ts1}.db"

    # Each item has the required keys.
    for item in items:
        assert "name" in item
        assert "size_bytes" in item
        assert "created_at" in item
        # created_at must be an ISO8601 string.
        assert isinstance(item["created_at"], str)
        assert "T" in item["created_at"] or "-" in item["created_at"]


def test_list_backups_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)
    # No backups dir has been created yet.
    assert bk.list_backups() == []


# ---------------------------------------------------------------------------
# prune_backups
# ---------------------------------------------------------------------------

def test_prune_backups_keeps_newest_n(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    for i in range(5):
        bk.create_backup(f"2026-06-19T{i:02d}0000")
        time.sleep(0.05)

    deleted = bk.prune_backups(2)
    assert deleted == 3

    remaining = bk.list_backups()
    assert len(remaining) == 2
    # The two most-recently-created files survive.
    assert remaining[0]["name"] == "plugtrack-2026-06-19T040000.db"
    assert remaining[1]["name"] == "plugtrack-2026-06-19T030000.db"


def test_prune_backups_zero_deletes_nothing(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    for i in range(3):
        bk.create_backup(f"2026-06-19T{i:02d}0000")
        time.sleep(0.05)

    deleted = bk.prune_backups(0)
    assert deleted == 0
    assert len(bk.list_backups()) == 3


def test_prune_backups_negative_deletes_nothing(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    for i in range(2):
        bk.create_backup(f"2026-06-19T{i:02d}0000")
        time.sleep(0.05)

    deleted = bk.prune_backups(-1)
    assert deleted == 0
    assert len(bk.list_backups()) == 2


def test_prune_backups_never_deletes_only_backup(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    bk.create_backup("2026-06-19T000000")
    # Even with retention=1, the single backup must not be pruned.
    deleted = bk.prune_backups(1)
    assert deleted == 0
    assert len(bk.list_backups()) == 1


def test_prune_backups_retention_larger_than_count(tmp_path, monkeypatch):
    src = tmp_path / "plugtrack.db"
    _make_db(src)
    monkeypatch.setattr(bk, "_source_db_path", lambda: src)
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)

    for i in range(3):
        bk.create_backup(f"2026-06-19T{i:02d}0000")
        time.sleep(0.05)

    # Retention larger than number of files → delete nothing.
    deleted = bk.prune_backups(10)
    assert deleted == 0
    assert len(bk.list_backups()) == 3


# ---------------------------------------------------------------------------
# backups_dir
# ---------------------------------------------------------------------------

def test_backups_dir_is_created_on_access(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "_data_dir", lambda: tmp_path)
    d = bk.backups_dir()
    assert d == tmp_path / "backups"
    assert d.is_dir()
