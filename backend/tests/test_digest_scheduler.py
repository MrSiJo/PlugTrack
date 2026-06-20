"""Tests for the digest-tick scheduler registration (Task 4).

Verifies that the lifespan always registers an hourly "digest-tick" job on
the app-level scheduler, regardless of whether backups are enabled.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Test 1: digest-tick job is registered during lifespan boot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_digest_tick_job_registered_in_lifespan(app):
    """The lifespan must register a job with id 'digest-tick' on app.state.scheduler."""
    async with app.router.lifespan_context(app):
        scheduler = getattr(app.state, "scheduler", None)
        assert scheduler is not None, "app.state.scheduler must be set"
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "digest-tick" in job_ids, (
            f"'digest-tick' not found among scheduler jobs: {job_ids!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: backup job is still registered when backups are enabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backup_job_registered_when_backup_enabled(app):
    """The 'backup-scheduled' job must still be registered when backup_enabled=true."""
    async with app.router.lifespan_context(app):
        scheduler = getattr(app.state, "scheduler", None)
        assert scheduler is not None, "app.state.scheduler must be set"
        job_ids = {j.id for j in scheduler.get_jobs()}
        # backup_enabled defaults to True, so the backup job must also be there
        assert "backup-scheduled" in job_ids, (
            f"'backup-scheduled' not found among scheduler jobs: {job_ids!r}"
        )


# ---------------------------------------------------------------------------
# Test 3: digest-tick is registered even when backups are disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_digest_tick_registered_when_backup_disabled(app, test_sessionmaker):
    """digest-tick must be scheduled even when backup_enabled=false."""
    from plugtrack.settings.seeds import seed_defaults
    from plugtrack.models.setting import Setting
    from sqlalchemy import select as _select

    # Disable backups in DB.
    async with test_sessionmaker() as session:
        await seed_defaults(session)
        await session.commit()
        row = (await session.execute(
            _select(Setting).where(Setting.key == "backup_enabled")
        )).scalar_one_or_none()
        if row is not None:
            row.value = "false"
        else:
            session.add(Setting(key="backup_enabled", value="false"))
        await session.commit()

    async with app.router.lifespan_context(app):
        scheduler = getattr(app.state, "scheduler", None)
        assert scheduler is not None, "app.state.scheduler must be set even when backups disabled"
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "digest-tick" in job_ids, (
            f"'digest-tick' must be scheduled regardless of backup_enabled; got {job_ids!r}"
        )
        # Backup job must NOT be registered
        assert "backup-scheduled" not in job_ids, (
            f"'backup-scheduled' must not be scheduled when backup_enabled=false; got {job_ids!r}"
        )
