"""Backfill a missed ChargingSession via the service-layer code path.

For when a charge happened but PlugTrack's sync never observed the
cable-connected window (Cupra Connect didn't push fresh telemetry, the
whole cycle fit between two idle polls, etc.) and the post-3.x phantom
detector wasn't there or didn't trigger.

The script uses the same `compute_session_cost` and ORM models the API
route uses, so the resulting row is identical to one created via the
UI's New Session form. `source` is always `"manual"`.

Usage (inside the plugtrack-api container):

    # 1. Always start with a dry run.
    python /app/scripts/backfill_session.py \\
        --car-id 1 \\
        --date 2026-05-14 \\
        --start-at 2026-05-14T11:18:00+00:00 \\
        --end-at   2026-05-14T11:43:00+00:00 \\
        --start-soc 60 --end-soc 86 \\
        --kwh-added 18.0 \\
        --total-cost-p 1199 \\
        --charging-type dc \\
        --charge-network MFG \\
        --location-id 4 \\
        --label "Public rapid"

    # 2. When the dry-run output looks right, repeat with --commit.

The --location-id is optional: omit it to leave the row unattached, and
edit later via PUT /api/sessions/{id} once the location row exists.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Optional

# Ensure the backend package is importable when run via `docker exec`.
sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from plugtrack.db import SessionLocal  # noqa: E402
from plugtrack.models import (  # noqa: E402
    Car,
    ChargingSession,
    Location,
    Setting,
)
from plugtrack.services.cost import compute_session_cost  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill a missed ChargingSession.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    required = p.add_argument_group("required")
    required.add_argument("--car-id", type=int, required=True)
    required.add_argument(
        "--date",
        type=date_cls.fromisoformat,
        required=True,
        help="Session date (YYYY-MM-DD).",
    )
    required.add_argument(
        "--start-soc", type=int, required=True,
        help="Start SoC percentage (0-100).",
    )
    required.add_argument(
        "--end-soc", type=int, required=True,
        help="End SoC percentage (0-100).",
    )
    required.add_argument(
        "--kwh-added", type=float, required=True,
        help="kWh delivered (charger reading, or compute from SoC delta).",
    )

    timing = p.add_argument_group("timing (optional, but recommended)")
    timing.add_argument(
        "--start-at", type=datetime.fromisoformat, default=None,
        help="Charge start timestamp (ISO 8601, include tz). Optional.",
    )
    timing.add_argument(
        "--end-at", type=datetime.fromisoformat, default=None,
        help="Charge end timestamp. Optional.",
    )

    cost = p.add_argument_group("cost (pick zero or one)")
    cost_group = cost.add_mutually_exclusive_group()
    cost_group.add_argument(
        "--total-cost-p", type=int, default=None,
        help="Total cost override in pence (cost_basis=override_total).",
    )
    cost_group.add_argument(
        "--per-kwh-p", type=float, default=None,
        help="Per-kWh override in pence (cost_basis=override_per_kwh).",
    )

    meta = p.add_argument_group("metadata")
    meta.add_argument(
        "--charging-type", choices=("ac", "dc", "unknown"), default="unknown",
    )
    meta.add_argument(
        "--charging-mode", default="unknown",
        help="Free-text charging mode label (default unknown).",
    )
    meta.add_argument("--charge-network", default=None)
    meta.add_argument(
        "--location-id", type=int, default=None,
        help="Optional Location.id to link the session to.",
    )
    meta.add_argument(
        "--odometer-km", type=float, default=None,
        help="Odometer reading at session in km.",
    )
    meta.add_argument(
        "--label", default=None,
        help="Short user_label for the session (e.g. station name).",
    )
    meta.add_argument(
        "--notes", default=None,
        help="Free-text notes. Defaults to a 'backfilled' marker.",
    )

    p.add_argument(
        "--commit", action="store_true",
        help="Actually write to the DB. Without this flag the script does a dry run.",
    )
    return p


def _validate_soc(args: argparse.Namespace) -> None:
    for name in ("start_soc", "end_soc"):
        v = getattr(args, name)
        if not 0 <= v <= 100:
            raise SystemExit(f"--{name.replace('_', '-')} must be 0..100, got {v}")
    if args.end_soc < args.start_soc:
        raise SystemExit(
            f"--end-soc ({args.end_soc}) is below --start-soc ({args.start_soc})"
        )
    if args.kwh_added <= 0:
        raise SystemExit("--kwh-added must be > 0")


async def _home_rate(session) -> float:
    row = (
        await session.execute(
            select(Setting).where(Setting.key == "default_home_rate_p_per_kwh")
        )
    ).scalar_one_or_none()
    if row is None or row.value is None:
        return 0.0
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return 0.0


async def _run(args: argparse.Namespace) -> None:
    async with SessionLocal() as s:
        car = await s.get(Car, args.car_id)
        if car is None:
            raise SystemExit(f"no car with id={args.car_id}")
        print(
            f"car: id={car.id} user_id={car.user_id} "
            f"{car.make} {car.model} battery={car.battery_kwh} kWh"
        )

        location: Optional[Location] = None
        if args.location_id is not None:
            location = await s.get(Location, args.location_id)
            if location is None or location.user_id != car.user_id:
                raise SystemExit(
                    f"location id={args.location_id} not found for this user"
                )
            print(f"location: id={location.id} name={location.name!r}")
        else:
            print("location: (none — link later via PUT /api/sessions/{id})")

        home_rate = await _home_rate(s)
        cost_pence, cost_basis, tariff = compute_session_cost(
            kwh_added=args.kwh_added,
            location=location,
            session_overrides={
                "cost_per_kwh_override_p": args.per_kwh_p,
                "total_cost_pence_override": args.total_cost_p,
            },
            settings_default_home_rate_p_per_kwh=home_rate,
        )
        print(
            f"cost compute -> cost_pence={cost_pence} "
            f"basis={cost_basis} tariff_p={tariff}"
        )

        notes = args.notes or (
            "backfilled - the sync pipeline did not observe the cable-connected window"
        )

        # kwh_calculated is the energy banked in the pack — derived
        # from SoC delta × battery_kwh. Distinct from kwh_added (the
        # charger's reading) so efficiency_percent in the UI means
        # something. Clamp at zero if end_soc < start_soc.
        soc_delta = max(0, args.end_soc - args.start_soc)
        kwh_calculated = round(soc_delta / 100.0 * float(car.battery_kwh), 2)

        cs = ChargingSession(
            user_id=car.user_id,
            car_id=car.id,
            plug_in_record_id=None,
            location_id=args.location_id,
            date=args.date,
            charge_start_at=args.start_at,
            charge_end_at=args.end_at,
            start_soc=args.start_soc,
            end_soc=args.end_soc,
            kwh_added=args.kwh_added,
            kwh_calculated=kwh_calculated,
            odometer_at_session_km=args.odometer_km,
            charging_type=args.charging_type,
            charging_mode=args.charging_mode,
            interrupted=False,
            cost_per_kwh_override_p=args.per_kwh_p,
            total_cost_pence_override=args.total_cost_p,
            charge_network=args.charge_network,
            user_label=args.label,
            notes=notes,
            source="manual",
            cost_pence=cost_pence,
            cost_basis=cost_basis,
            tariff_p_per_kwh=tariff,
        )
        s.add(cs)
        await s.flush()
        print(f"prepared ChargingSession id={cs.id}:")
        print(
            f"  date={cs.date}  start={cs.charge_start_at}  end={cs.charge_end_at}"
        )
        print(
            f"  soc {cs.start_soc} -> {cs.end_soc}  kwh_added={cs.kwh_added}  "
            f"type={cs.charging_type}"
        )
        print(f"  network={cs.charge_network}  label={cs.user_label!r}")
        print(f"  cost_pence={cs.cost_pence}  basis={cs.cost_basis}")

        if args.commit:
            await s.commit()
            print("COMMITTED")
        else:
            await s.rollback()
            print("DRY RUN -- rolled back, no changes persisted. Re-run with --commit.")


def main() -> None:
    args = _build_parser().parse_args()
    _validate_soc(args)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
