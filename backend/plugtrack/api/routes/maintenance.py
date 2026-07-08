"""Maintenance routes — backup, list, download, and sessions export.

All routes are auth-gated by AuthMiddleware (no EXEMPT_PATHS additions).
Mutating routes (POST /backup) are also CSRF-gated.

Endpoints
---------
POST /api/maintenance/backup
    Run create_backup via asyncio.to_thread, then prune_backups(retention).
    Returns {name, size_bytes, created_at}.

GET  /api/maintenance/backups
    List all backups newest-first.

GET  /api/maintenance/backups/{name}/download
    FileResponse. Traversal-safe: validate name pattern, resolve path,
    assert is_relative_to(backups_dir()), 404 if missing, 400 if bad pattern.

GET  /api/maintenance/export/sessions?format=csv|json
    StreamingResponse of the caller's sessions.  User isolation enforced by
    passing request.state.user_id into export_sessions_rows.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Setting
from ...services.backup import backups_dir, create_backup, list_backups, prune_backups
from ...services.export import (
    SESSION_EXPORT_COLUMNS,
    export_sessions_rows,
    rows_to_csv,
    rows_to_json,
)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

# Allowlist pattern for backup filenames — prevents path traversal.
_BACKUP_NAME_RE = re.compile(r"^plugtrack-[0-9T\-]+\.db$")

_DEFAULT_RETENTION = 7


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def _get_retention(db: AsyncSession) -> int:
    """Read backup_retention from the Setting table; default to 7 if absent/blank."""
    row = (
        await db.execute(select(Setting).where(Setting.key == "backup_retention"))
    ).scalar_one_or_none()
    if row is None or not row.value:
        return _DEFAULT_RETENTION
    try:
        return int(row.value)
    except (ValueError, TypeError):
        return _DEFAULT_RETENTION


# ---------------------------------------------------------------------------
# POST /api/maintenance/backup
# ---------------------------------------------------------------------------


@router.post("/backup")
async def run_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a VACUUM INTO snapshot and prune old backups.

    The VACUUM is run via asyncio.to_thread so the event loop stays free.
    Returns {name, size_bytes, created_at} for the new backup.
    """
    _user_id(request)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    meta = await asyncio.to_thread(create_backup, ts)

    retention = await _get_retention(db)
    await asyncio.to_thread(prune_backups, retention)

    # created_at from mtime of the backup we just created.
    from pathlib import Path

    dest = Path(meta["path"])
    import os

    mtime = os.path.getmtime(dest)
    created_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()

    return {
        "name": meta["name"],
        "size_bytes": meta["size_bytes"],
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# GET /api/maintenance/backups
# ---------------------------------------------------------------------------


@router.get("/backups")
async def get_backups(request: Request) -> list[dict]:
    """List all backup files, newest first."""
    _user_id(request)
    return list_backups()


# ---------------------------------------------------------------------------
# GET /api/maintenance/backups/{name}/download
# ---------------------------------------------------------------------------


@router.get("/backups/{name}/download")
async def download_backup(name: str, request: Request) -> FileResponse:
    """Serve a backup file.

    Traversal safety:
    1. Validate *name* against ^plugtrack-[0-9T\\-]+\\.db$.
    2. Resolve path = backups_dir() / name.
    3. Assert resolved path is inside backups_dir().resolve().
    4. 404 if the file doesn't exist; 400 if name fails the pattern.
    """
    _user_id(request)

    if not _BACKUP_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    base = backups_dir().resolve()
    resolved = (base / name).resolve()

    if not resolved.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Path traversal detected")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    return FileResponse(
        path=resolved,
        media_type="application/octet-stream",
        filename=name,
    )


# ---------------------------------------------------------------------------
# GET /api/maintenance/export/sessions
# ---------------------------------------------------------------------------


@router.get("/export/sessions")
async def export_sessions(
    request: Request,
    format: str = Query(default="csv"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export all charging sessions for the authenticated user.

    Query param:
        format  csv (default) | json

    Returns a file download with Content-Disposition set.
    """
    uid = _user_id(request)

    if format not in ("csv", "json"):
        raise HTTPException(
            status_code=400,
            detail="format must be 'csv' or 'json'",
        )

    rows = await export_sessions_rows(db, uid)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    if format == "csv":
        content = rows_to_csv(SESSION_EXPORT_COLUMNS, rows)
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (f'attachment; filename="plugtrack-sessions-{today}.csv"')
            },
        )
    else:
        content = rows_to_json(rows)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": (f'attachment; filename="plugtrack-sessions-{today}.json"')
            },
        )
