"""One-shot: authenticate against Cupra Connect and print your VINs.

Reads credentials from `.env.probe` at the repo root (same file as the
Phase 0 harness). Output is the VIN string you should paste into
`provider_vehicle_id` when creating a car in PlugTrack.

Usage:
    .venv/Scripts/python.exe scripts/list_cupra_vins.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env_probe() -> dict[str, str]:
    path = REPO_ROOT / ".env.probe"
    if not path.exists():
        sys.exit(f"missing {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


async def main() -> None:
    creds_env = load_env_probe()
    username = creds_env.get("CUPRA_USERNAME") or creds_env.get("PROBE_CUPRA_USERNAME")
    password = creds_env.get("CUPRA_PASSWORD") or creds_env.get("PROBE_CUPRA_PASSWORD")
    spin = creds_env.get("CUPRA_SPIN") or creds_env.get("PROBE_CUPRA_SPIN")
    if not username or not password:
        sys.exit("CUPRA_USERNAME and CUPRA_PASSWORD must be set in .env.probe")

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from plugtrack.plugins.pycupra.adapter import authenticate
    from plugtrack.plugins.pycupra.models import Credentials

    creds = Credentials(username=username, password=password, spin=spin or None)
    with tempfile.TemporaryDirectory() as td:
        connection = await authenticate(creds, token_dir=Path(td))
        await connection.get_vehicles()
        print()
        print("Vehicles on this account:")
        print("-" * 60)
        vehicles_iter = []
        if isinstance(getattr(connection, "_vehicles", None), list):
            vehicles_iter = connection._vehicles
        elif isinstance(getattr(connection, "_vehicles", None), dict):
            vehicles_iter = list(connection._vehicles.values())
        for v in vehicles_iter:
            vin = getattr(v, "vin", None) or getattr(v, "_vin", None) or "?"
            model = getattr(v, "model", None) or "(unknown model)"
            year = getattr(v, "modelYear", None) or ""
            print(f"  VIN: {vin}    {model} {year}".rstrip())
        try:
            await connection.logout()
        except Exception:
            pass
        print()
        print("Paste the VIN into the 'Provider vehicle ID' field on the Cars page.")


if __name__ == "__main__":
    asyncio.run(main())
