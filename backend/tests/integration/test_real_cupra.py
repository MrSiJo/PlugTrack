"""Real-account integration test for the pycupra adapter (Phase 5.6).

GATED. Skipped unless **both**:
- `INTEGRATION=1` is set in the env, AND
- `.env.probe` exists at the repo root with valid Cupra Connect creds.

Use this test as a smoke-test after bumping the pycupra dependency:

    INTEGRATION=1 pytest backend/tests/integration -v

The test goes through the live pycupra OAuth → fetch_vehicle_state
round-trip and asserts the returned `VehicleState` looks plausible.
Token cache lives in `tmp_path` so dev-cache is never polluted.

DO NOT commit `.env.probe`. The file is gitignored.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest


def _repo_root() -> Path:
    # backend/tests/integration/test_real_cupra.py → repo root is up 3.
    return Path(__file__).resolve().parents[3]


def _load_env_probe() -> dict:
    """Parse the repo-root .env.probe file into a flat dict.

    Tiny parser; no support for multi-line values or interpolation —
    keys/values are stripped of surrounding whitespace + matching
    quote characters. Lines starting with `#` and blank lines are
    ignored.
    """
    path = _repo_root() / ".env.probe"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


@pytest.mark.asyncio
async def test_real_cupra_authenticate_and_fetch_state(tmp_path):
    if os.getenv("INTEGRATION") != "1":
        pytest.skip("set INTEGRATION=1 to run real-account tests")

    creds = _load_env_probe()
    if not creds.get("CUPRA_USERNAME") or not creds.get("CUPRA_PASSWORD"):
        pytest.skip(".env.probe missing — needs CUPRA_USERNAME + CUPRA_PASSWORD")

    # Local imports so collecting this file when INTEGRATION is unset
    # never pulls pycupra in.
    from plugtrack.plugins.pycupra.adapter import (
        authenticate,
        fetch_vehicle_state,
    )
    from plugtrack.plugins.pycupra.models import Credentials

    connection = await authenticate(
        Credentials(
            username=creds["CUPRA_USERNAME"],
            password=creds["CUPRA_PASSWORD"],
            spin=creds.get("CUPRA_SPIN") or None,
        ),
        token_dir=tmp_path,
    )

    vehicles = await connection.get_vehicles()
    assert vehicles, "pycupra returned no vehicles for the account"
    first = vehicles[0]
    vehicle_id = getattr(first, "vin", None) or getattr(first, "unique_id", None)
    assert vehicle_id, "vehicle has no vin/unique_id"

    state = await fetch_vehicle_state(connection, vehicle_id)

    # Basic sanity assertions. Cupra can sometimes return 0 SoC for very
    # stale telemetry; the test is written to catch outright wiring bugs
    # (e.g. defaults silently masking real values), not to second-guess
    # plausible API behaviour.
    assert state.battery_level >= 0
    assert state.battery_level <= 100
    assert isinstance(state.charging_cable_connected, bool)
    assert state.target_soc is None or (0 <= state.target_soc <= 100)
    assert isinstance(state.last_connected, datetime)
