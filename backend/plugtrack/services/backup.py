"""SQLite snapshot service — whole-DB VACUUM INTO backups.

Public interface
----------------
backups_dir()          -> Path          : data_dir/backups (auto-created)
create_backup(ts: str) -> dict          : VACUUM INTO snapshot; returns metadata
list_backups()         -> list[dict]    : newest-first list of backup metadata
prune_backups(n: int)  -> int           : keep newest n; return count deleted

Design notes
------------
- VACUUM INTO is SQLite-sync — we use the stdlib ``sqlite3`` module directly on
  the source file path (NOT the async aiosqlite engine).  The caller (a later
  scheduler task) must run ``create_backup`` via ``asyncio.to_thread`` to keep
  the event loop unblocked.
- Backups are whole-DB files (not per-user).  This is acceptable for a
  single-user homelab install.  All auth-gated routes that serve these files
  must still be behind normal middleware.
- VACUUM INTO does not accept a bound ``?`` parameter in all SQLite versions,
  so the destination path is embedded as a string literal.  The path is
  entirely server-controlled (data_dir + a server-supplied timestamp) with no
  user input, so injection is not a concern; single quotes are escaped
  defensively anyway.

Internal helpers
----------------
``_source_db_path()`` and ``_data_dir()`` are small callables so that tests can
monkeypatch them without replacing the whole settings object.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from plugtrack.bootstrap import get_settings

# ---------------------------------------------------------------------------
# Internal helpers — monkeypatchable by tests
# ---------------------------------------------------------------------------


def _data_dir() -> Path:
    """Return the data directory as a Path object."""
    return Path(get_settings().data_dir)


def _source_db_path() -> Path:
    """Resolve the source SQLite file path from the database URL.

    The database_url looks like ``sqlite+aiosqlite:///abs/path/plugtrack.db``.
    Strip the driver prefix to get the raw file path.  Falls back to
    ``data_dir/plugtrack.db`` if the URL doesn't start with the expected prefix.
    """
    url = get_settings().database_url
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        return Path(url[len(prefix) :])
    return _data_dir() / "plugtrack.db"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def backups_dir() -> Path:
    """Return the backups directory, creating it (parents / exist_ok) on first access."""
    d = _data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(timestamp: str) -> dict:
    """Create a VACUUM INTO snapshot of the live database.

    Parameters
    ----------
    timestamp:
        A safe filename component such as ``"2026-06-19T120000"``.  The backup
        is written to ``backups_dir()/plugtrack-<timestamp>.db``.

    Returns
    -------
    dict with keys:
        name        : filename only (e.g. ``"plugtrack-2026-06-19T120000.db"``)
        path        : absolute path string of the backup file
        size_bytes  : file size in bytes after the VACUUM
    """
    dest_dir = backups_dir()
    name = f"plugtrack-{timestamp}.db"
    dest = dest_dir / name

    src = _source_db_path()

    # Embed the destination path as a string literal (not a bound parameter —
    # VACUUM INTO rejects ? in some SQLite versions).  Escape single quotes
    # defensively even though the path is server-controlled.
    safe_dest = str(dest).replace("'", "''")
    conn = sqlite3.connect(src)
    try:
        conn.execute(f"VACUUM INTO '{safe_dest}'")
    finally:
        conn.close()

    size = dest.stat().st_size
    return {"name": name, "path": str(dest), "size_bytes": size}


def list_backups() -> list[dict]:
    """Return metadata for all backup files, sorted newest-first by mtime.

    Returns an empty list if the backups directory does not exist yet.
    """
    d = _data_dir() / "backups"
    if not d.exists():
        return []

    files = sorted(d.glob("plugtrack-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        st = f.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC)
        result.append(
            {
                "name": f.name,
                "size_bytes": st.st_size,
                "created_at": mtime.isoformat(),
            }
        )
    return result


def prune_backups(retention_n: int) -> int:
    """Delete backup files beyond the newest *retention_n*, oldest first.

    Guards
    ------
    - ``retention_n <= 0`` → no-op (returns 0).
    - Never deletes the only remaining backup.
    - Never deletes the newest backup (it is always preserved).

    Returns
    -------
    int : number of files actually deleted.
    """
    if retention_n <= 0:
        return 0

    d = _data_dir() / "backups"
    if not d.exists():
        return 0

    # Sort newest-first by mtime.
    files = sorted(d.glob("plugtrack-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

    if len(files) <= 1:
        # Never delete the only / newest backup.
        return 0

    to_delete = files[retention_n:]  # everything beyond the newest N
    deleted = 0
    for f in to_delete:
        # Safety: never delete files[0] (the newest), though slicing above
        # guarantees this as long as retention_n >= 1.
        if f == files[0]:
            continue
        f.unlink(missing_ok=True)
        deleted += 1
    return deleted
