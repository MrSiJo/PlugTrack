"""Smoke tests for seed_demo.py.

Seeds a temp demo DB in a pytest tmp_path and asserts:
- ≥ 2 cars (at least 1 archived)
- ≥ 5 locations
- ≥ 30 sessions
- ≥ 1 session with a power_curve
- ≥ 1 session with cost_basis == "location_free"
- A CarMileageYear row exists for the active car
- window_totals returns sessions > 0
- network_breakdown returns > 1 network

Runs in the default suite (no special env var needed) and is fast
(in-memory seeding, no network calls).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure backend root is importable
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault("APP_SECRET_KEY", "demo-seed-test-secret-key-padding-padding-padding")


@pytest.mark.asyncio
async def test_seed_demo_smoke(tmp_path):
    """Seed a demo DB and verify all structural invariants."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # Must use a path whose basename contains "demo"
    demo_db = tmp_path / "demo_test.db"

    from plugtrack.scripts.seed_demo import seed
    await seed(demo_db)

    url = f"sqlite+aiosqlite:///{demo_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        from plugtrack.models import Car, CarMileageYear, ChargingSession, Location

        # --- Cars ---
        cars = (await s.execute(select(Car))).scalars().all()
        assert len(cars) >= 2, f"Expected ≥ 2 cars, got {len(cars)}"
        archived = [c for c in cars if not c.active]
        assert len(archived) >= 1, "Expected at least 1 archived car"

        # --- Locations ---
        locs = (await s.execute(select(Location))).scalars().all()
        assert len(locs) >= 5, f"Expected ≥ 5 locations, got {len(locs)}"

        # --- Sessions ---
        sessions = (await s.execute(select(ChargingSession))).scalars().all()
        assert len(sessions) >= 30, f"Expected ≥ 30 sessions, got {len(sessions)}"

        # --- Power curve ---
        curve_sessions = [s2 for s2 in sessions if s2.power_curve is not None]
        assert len(curve_sessions) >= 1, "Expected ≥ 1 session with a power_curve"

        # --- Free sessions ---
        free_sessions = [s2 for s2 in sessions if s2.cost_basis == "location_free"]
        assert len(free_sessions) >= 1, "Expected ≥ 1 session with cost_basis='location_free'"

        # --- Mileage year ---
        active_cars = [c for c in cars if c.active]
        assert active_cars, "No active car found"
        mileage_rows = (await s.execute(
            select(CarMileageYear).where(CarMileageYear.car_id == active_cars[0].id)
        )).scalars().all()
        assert len(mileage_rows) >= 1, "Expected a CarMileageYear row for the active car"

        # --- window_totals aggregator ---
        from plugtrack.models import User
        user = (await s.execute(select(User))).scalars().first()
        assert user is not None

        from plugtrack.services.insights_stats import network_breakdown, window_totals
        totals = await window_totals(s, user_id=user.id, lo=None, hi=None)
        assert totals["sessions"] > 0, f"window_totals sessions == 0: {totals}"

        # --- network_breakdown aggregator ---
        nets = await network_breakdown(s, user_id=user.id, date_from=None, date_to=None)
        assert len(nets) > 1, f"Expected > 1 network in breakdown, got {len(nets)}: {nets}"

    await engine.dispose()


def test_seed_demo_safety_guard(tmp_path):
    """Seeding to a path without 'demo' in the basename must fail."""
    import subprocess

    bad_path = tmp_path / "plugtrack.db"
    result = subprocess.run(
        [sys.executable, "-m", "plugtrack.scripts.seed_demo", "--db", str(bad_path)],
        cwd=str(_BACKEND_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "APP_SECRET_KEY": "demo-seed-test-secret-key-padding-padding-padding"},
    )
    assert result.returncode != 0, "Safety guard did not exit non-zero"
    assert "demo" in result.stderr.lower() or "refusing" in result.stderr.lower(), (
        f"Expected refusal message in stderr, got: {result.stderr!r}"
    )
