"""Tests for /api/maintenance/* endpoints.

Covers:
- POST /api/maintenance/backup  (creates backup, prunes on retention=1)
- GET  /api/maintenance/backups (lists backups)
- GET  /api/maintenance/backups/{name}/download (valid + traversal attacks)
- GET  /api/maintenance/export/sessions (csv/json, user isolation, bad format)
- Unauthenticated requests → 401
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tests.api.conftest import csrf_headers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# POST /api/maintenance/backup
# ---------------------------------------------------------------------------


def _make_real_sqlite(path: Path) -> Path:
    """Create a minimal but valid SQLite database file at *path*."""
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(path)
    conn.execute("CREATE TABLE _dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return path


@pytest.mark.asyncio
async def test_backup_creates_file(authed_client, tmp_path, monkeypatch):
    """POST /api/maintenance/backup → 200, returns metadata, file exists on disk."""
    from plugtrack.services import backup as backup_svc

    # Redirect backups dir to tmp_path so we don't litter the real data_dir.
    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)
    # The VACUUM source must be a real SQLite file.
    fake_db = _make_real_sqlite(tmp_path / "plugtrack.db")
    monkeypatch.setattr(backup_svc, "_source_db_path", lambda: fake_db)

    r = await authed_client.post(
        "/api/maintenance/backup",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "name" in body
    assert "size_bytes" in body
    assert "created_at" in body
    assert body["name"].startswith("plugtrack-")
    assert body["name"].endswith(".db")

    # File must exist on disk.
    backup_file = tmp_path / "backups" / body["name"]
    assert backup_file.exists(), f"Expected {backup_file} to exist"


@pytest.mark.asyncio
async def test_backup_prunes_to_retention(authed_client, test_sessionmaker, tmp_path, monkeypatch):
    """Two backups + retention=1 → only one file remains after second POST.

    Strategy: create the first backup directly via the service (bypassing the
    route) so we control the timestamp.  Then call the route for the second
    backup after inserting backup_retention=1 in the DB.  The prune should
    remove the older file, leaving only the newest.
    """
    from plugtrack.models import Setting
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)
    fake_db = _make_real_sqlite(tmp_path / "plugtrack.db")
    monkeypatch.setattr(backup_svc, "_source_db_path", lambda: fake_db)

    # Create the first backup directly (timestamp = "20260101T000000").
    meta1 = backup_svc.create_backup("20260101T000000")
    assert (tmp_path / "backups" / meta1["name"]).exists()

    # Insert backup_retention=1 directly into the test DB.
    async with test_sessionmaker() as session:
        row = (
            await session.execute(
                __import__("sqlalchemy").select(Setting).where(Setting.key == "backup_retention")
            )
        ).scalar_one_or_none()
        if row is not None:
            row.value = "1"
        else:
            session.add(
                Setting(
                    key="backup_retention",
                    value="1",
                    value_type="integer",
                    group_name="maintenance",
                    label="Backup retention",
                )
            )
        await session.commit()

    # Patch the route's datetime so the second backup gets a distinct timestamp.
    from unittest.mock import MagicMock, patch

    import plugtrack.api.routes.maintenance as maint_routes

    fixed_dt = MagicMock()
    fixed_dt.now.return_value.strftime.return_value = "20260619T120000"
    with patch.object(maint_routes, "datetime", fixed_dt):
        r2 = await authed_client.post(
            "/api/maintenance/backup",
            headers=csrf_headers(authed_client),
        )

    assert r2.status_code == 200, r2.text
    second_name = r2.json()["name"]

    # After prune with retention=1, only the newest backup should remain.
    backups_dir_path = tmp_path / "backups"
    remaining = list(backups_dir_path.glob("plugtrack-*.db"))
    assert len(remaining) == 1, f"Expected 1 file after prune, got {[f.name for f in remaining]}"
    assert (backups_dir_path / second_name).exists(), "Newest backup must survive pruning"


@pytest.mark.asyncio
async def test_backup_requires_auth(seeded_client):
    """POST /api/maintenance/backup without a session cookie → 401."""
    r = await seeded_client.post("/api/maintenance/backup")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/maintenance/backups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_backups_empty(authed_client, tmp_path, monkeypatch):
    """GET /api/maintenance/backups returns [] when no backups exist."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)

    r = await authed_client.get("/api/maintenance/backups")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_backups_shows_created(authed_client, tmp_path, monkeypatch):
    """After a backup, GET /api/maintenance/backups lists it."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)
    fake_db = _make_real_sqlite(tmp_path / "plugtrack.db")
    monkeypatch.setattr(backup_svc, "_source_db_path", lambda: fake_db)

    create_r = await authed_client.post(
        "/api/maintenance/backup",
        headers=csrf_headers(authed_client),
    )
    assert create_r.status_code == 200
    created_name = create_r.json()["name"]

    list_r = await authed_client.get("/api/maintenance/backups")
    assert list_r.status_code == 200
    names = [item["name"] for item in list_r.json()]
    assert created_name in names


@pytest.mark.asyncio
async def test_list_backups_requires_auth(seeded_client):
    r = await seeded_client.get("/api/maintenance/backups")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/maintenance/backups/{name}/download
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_valid_backup(authed_client, tmp_path, monkeypatch):
    """Download a valid backup → 200, bytes returned."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)
    fake_db = _make_real_sqlite(tmp_path / "plugtrack.db")
    monkeypatch.setattr(backup_svc, "_source_db_path", lambda: fake_db)

    create_r = await authed_client.post(
        "/api/maintenance/backup",
        headers=csrf_headers(authed_client),
    )
    name = create_r.json()["name"]

    dl_r = await authed_client.get(f"/api/maintenance/backups/{name}/download")
    assert dl_r.status_code == 200
    assert len(dl_r.content) > 0


@pytest.mark.asyncio
async def test_download_traversal_rejected(authed_client, tmp_path, monkeypatch):
    """../etc/passwd traversal → 400 (pattern mismatch)."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)

    r = await authed_client.get("/api/maintenance/backups/../etc/passwd/download")
    # FastAPI path normalisation may 404 before we even reach the handler,
    # but we must never get 200.
    assert r.status_code in (400, 404, 422)


@pytest.mark.asyncio
async def test_download_wrong_pattern_rejected(authed_client, tmp_path, monkeypatch):
    """foo.db doesn't match ^plugtrack-[0-9T\\-]+\\.db$ → 400."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)

    r = await authed_client.get("/api/maintenance/backups/foo.db/download")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_download_valid_pattern_nonexistent(authed_client, tmp_path, monkeypatch):
    """Valid pattern name that doesn't exist on disk → 404."""
    from plugtrack.services import backup as backup_svc

    monkeypatch.setattr(backup_svc, "_data_dir", lambda: tmp_path)

    r = await authed_client.get("/api/maintenance/backups/plugtrack-20260101T000000.db/download")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_download_requires_auth(seeded_client):
    r = await seeded_client.get("/api/maintenance/backups/plugtrack-20260101T000000.db/download")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/maintenance/export/sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_sessions_csv(authed_client, tmp_path, monkeypatch):
    """CSV export → 200, text/csv, header row present."""
    r = await authed_client.get("/api/maintenance/export/sessions?format=csv")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    # Header row must be present.
    text = r.text
    assert "id" in text
    assert "date" in text
    assert "kwh_added" in text
    # Content-Disposition header.
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".csv" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_sessions_json(authed_client):
    """JSON export → 200, application/json."""
    r = await authed_client.get("/api/maintenance/export/sessions?format=json")
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"]
    data = r.json()
    assert isinstance(data, list)
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".json" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_sessions_default_csv(authed_client):
    """format param defaults to csv."""
    r = await authed_client.get("/api/maintenance/export/sessions")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_export_sessions_bad_format(authed_client):
    """format=xml → 400."""
    r = await authed_client.get("/api/maintenance/export/sessions?format=xml")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_export_sessions_user_isolation(
    authed_client, app, other_user_headers, test_sessionmaker
):
    """Session belonging to user A must NOT appear in user B's export.

    We insert a ChargingSession for user A (the authed_client user) directly
    into the test DB, then call the export endpoint with a fresh client
    authenticated as user B, and assert user A's session data is absent.
    """
    from datetime import date as date_cls

    from httpx import ASGITransport, AsyncClient
    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME
    from plugtrack.models import Car, ChargingSession, User

    # Pull user A's id from the DB (authed_client user = "admin").
    async with test_sessionmaker() as session:
        from sqlalchemy import select

        users = (await session.execute(select(User))).scalars().all()
        admin_user = next(u for u in users if u.username == "admin")
        user_a_id = admin_user.id

        # Create a car for user A.
        car = Car(
            user_id=user_a_id,
            make="Tesla",
            model="Model3",
            battery_kwh=75.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)

        # Create a session for user A with a distinctive kwh_added value.
        cs = ChargingSession(
            user_id=user_a_id,
            car_id=car.id,
            date=date_cls(2026, 1, 15),
            start_soc=20,
            end_soc=80,
            kwh_added=99.9,  # distinctive -- must NOT appear in user B's export
            source="manual",
        )
        session.add(cs)
        await session.commit()

    # Build a fresh client authenticated as user B, so there's no conflict with
    # authed_client's cookie jar (which already has user A's session cookie).
    other_cookie_value = other_user_headers[SESSION_COOKIE_NAME]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as other_client:
        other_client.cookies.set(SESSION_COOKIE_NAME, other_cookie_value)
        r = await other_client.get("/api/maintenance/export/sessions?format=csv")

    assert r.status_code == 200
    assert "99.9" not in r.text, "User A's session must not appear in user B's export"


@pytest.mark.asyncio
async def test_export_sessions_requires_auth(seeded_client):
    r = await seeded_client.get("/api/maintenance/export/sessions")
    assert r.status_code == 401
