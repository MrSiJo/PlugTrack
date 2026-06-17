# backend/plugtrack/scripts/import_mycupra_csv.py
"""CLI to backfill sessions from a MyCupra charging-statistics CSV export.

Ships inside the package so it can run against the live DB in the container:

    docker compose -f compose-dev.yaml cp charging_statistics.csv plugtrack-api:/tmp/x.csv
    docker compose -f compose-dev.yaml exec plugtrack-api \\
        python -m plugtrack.scripts.import_mycupra_csv /tmp/x.csv            # dry-run
    docker compose -f compose-dev.yaml exec plugtrack-api \\
        python -m plugtrack.scripts.import_mycupra_csv /tmp/x.csv --apply    # write

Without --apply it is a what-if: it prints the plan and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Optional

from sqlalchemy import select

from ..models import Car, ChargingSession
from ..services.mycupra_import import (
    format_report, load_csv, parse_location_map, run_import,
)


async def _resolve_car(session, car_id: Optional[int]) -> tuple[int, int]:
    """Return (user_id, car_id). Defaults to the single active car."""
    if car_id is not None:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one_or_none()
        if car is None:
            raise SystemExit(f"car {car_id} not found")
        return car.user_id, car.id
    cars = list((await session.execute(
        select(Car).where(Car.active == True))).scalars().all())  # noqa: E712
    if len(cars) != 1:
        raise SystemExit(
            f"expected exactly one active car, found {len(cars)} — pass --car-id")
    return cars[0].user_id, cars[0].id


async def _run(args: argparse.Namespace) -> int:
    if args.database_url:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine = create_async_engine(args.database_url, future=True)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    else:
        from ..db import SessionLocal as sessionmaker  # configured engine

    rows = load_csv(args.csv_path)
    location_by_date = parse_location_map(args.location_map)
    delete_ids = [int(x) for x in (args.delete_session_id or [])]
    delete_lines: list[str] = []

    async with sessionmaker() as session:
        user_id, car_id = await _resolve_car(session, args.car_id)
        # Pre-import cleanup: drop explicitly-named sessions (e.g. a phantom
        # 0-kWh synthesis row). Scoped to this user+car for safety.
        for sid in delete_ids:
            cs = await session.get(ChargingSession, sid)
            if cs is None or cs.user_id != user_id or cs.car_id != car_id:
                delete_lines.append(f"  DELETE #{sid}: not found for this car — skipped")
                continue
            delete_lines.append(
                f"  DELETE #{sid}: {cs.date} {cs.start_soc}->{cs.end_soc}% "
                f"{cs.kwh_added}kWh {cs.source}")
            if args.apply:
                await session.delete(cs)
        if args.apply and delete_ids:
            await session.flush()

        report = await run_import(
            session, user_id=user_id, car_id=car_id, rows=rows, apply=args.apply,
            location_by_date=location_by_date)
        if args.apply:
            await session.commit()

    print(f"\nMyCupra import — car {car_id}, {len(rows)} CSV rows "
          f"({'APPLIED' if args.apply else 'DRY-RUN, no writes'}):\n")
    if delete_lines:
        print("Pre-import cleanup:")
        print("\n".join(delete_lines))
        print()
    if location_by_date:
        print("Inserted-row locations by date: "
              + ", ".join(f"{d}=loc{loc}" for d, loc in sorted(location_by_date.items())))
        print()
    print(format_report(report))
    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write these changes.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill sessions from a MyCupra CSV export.")
    p.add_argument("csv_path", help="path to charging_statistics_*.csv")
    p.add_argument("--car-id", type=int, default=None,
                   help="target car id (default: the single active car)")
    p.add_argument("--apply", action="store_true",
                   help="write changes (default: dry-run / what-if)")
    p.add_argument("--location-map", default=None,
                   help="assign inserted rows a location by local date, e.g. "
                        "'2026-06-10=8,2026-06-14=1'")
    p.add_argument("--delete-session-id", action="append", default=None,
                   help="session id to delete before importing (repeatable)")
    p.add_argument("--database-url", default=None,
                   help="override DATABASE_URL (default: app config)")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
