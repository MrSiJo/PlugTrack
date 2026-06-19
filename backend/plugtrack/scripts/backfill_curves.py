# backend/plugtrack/scripts/backfill_curves.py
"""CLI to backfill approximate charge curves onto existing sessions from
re-retrieved MyCupra screenshots, using the REAL vision-extraction pipeline.

Each image is run through `call_openai` — the same extraction the Telegram bot
uses — so this exercises (and validates) the live pipeline. The extracted
`power_curve` is matched to an existing session by start-time + SoC, mapped to
the renderer's `[t_seconds, soc, power_kw]` triplets, and written onto that
session's `power_curve` column. It writes ONLY `power_curve` — never cost, SoC,
kWh, or rate — so it stays clear of any cost re-rating. Idempotent: re-running
overwrites the curve.

    docker compose -f compose-dev.yaml cp ./curves plugtrack-api:/tmp/curves
    docker compose -f compose-dev.yaml exec plugtrack-api \\
        python -m plugtrack.scripts.backfill_curves /tmp/curves            # dry-run
    docker compose -f compose-dev.yaml exec plugtrack-api \\
        python -m plugtrack.scripts.backfill_curves /tmp/curves --apply    # write
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from ..models import Car, ChargingSession
from ..services.screenshot_commit import map_curve_points
from ..services.screenshot_correlation import _parse_dt
from ..services.screenshot_extraction import Extraction, call_openai
from ..services.telegram_ingest import read_raw_credentials

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _gather_images(paths: list[str]) -> list[str]:
    """Expand a mix of files and directories into a sorted list of image files."""
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(_IMG_EXTS):
                    out.append(os.path.join(p, name))
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return out


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo so screenshot (UTC-parsed) and DB (naive wall-clock) times
    compare as the same local wall-clock."""
    return dt.replace(tzinfo=None) if dt is not None else None


def pick_session(
    candidates: list[ChargingSession],
    ext_start: Optional[datetime],
    soc_start: Optional[int],
    soc_end: Optional[int],
    tol_min: int,
) -> Optional[ChargingSession]:
    """Best session whose start is within `tol_min` of the screenshot start,
    preferring an exact SoC-pair match, then the closest start time."""
    if ext_start is None:
        return None
    target = _naive(ext_start)
    best: Optional[ChargingSession] = None
    best_score: Optional[tuple] = None
    for cs in candidates:
        cs_start = _naive(cs.charge_start_at)
        if cs_start is None:
            continue
        delta = abs((cs_start - target).total_seconds())
        if delta > tol_min * 60:
            continue
        soc_ok = (soc_start is None or cs.start_soc == soc_start) and (
            soc_end is None or cs.end_soc == soc_end
        )
        score = (0 if soc_ok else 1, delta)
        if best_score is None or score < best_score:
            best_score, best = score, cs
    return best


async def _resolve_car(session, car_id: Optional[int]) -> tuple[int, int]:
    if car_id is not None:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one_or_none()
        if car is None:
            raise SystemExit(f"car {car_id} not found")
        return car.user_id, car.id
    cars = list((await session.execute(
        select(Car).where(Car.active == True))).scalars().all())  # noqa: E712
    if len(cars) != 1:
        raise SystemExit(f"expected exactly one active car, found {len(cars)} — pass --car-id")
    return cars[0].user_id, cars[0].id


def _curve_secs(cs: ChargingSession) -> Optional[int]:
    """The x-axis span for the curve — the ACTUAL charge time, falling back to
    the plug-in window only when actual is unknown."""
    if cs.actual_charge_seconds:
        return cs.actual_charge_seconds
    if cs.charge_end_at and cs.charge_start_at:
        return int((cs.charge_end_at - cs.charge_start_at).total_seconds())
    return None


async def _run(args: argparse.Namespace) -> int:
    if args.database_url:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine = create_async_engine(args.database_url, future=True)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    else:
        from ..db import SessionLocal as sessionmaker  # configured engine

    _token, openai_key, model = await read_raw_credentials(sessionmaker)
    if not openai_key:
        raise SystemExit("no openai_api_key in settings — cannot run extraction")
    model = model or "gpt-5-mini"

    images = _gather_images(args.images)
    print(f"Curve backfill — model {model}, {len(images)} image(s) "
          f"({'APPLY' if args.apply else 'DRY-RUN, no writes'}):\n")

    written = 0
    async with sessionmaker() as session:
        user_id, car_id = await _resolve_car(session, args.car_id)
        candidates = list((await session.execute(
            select(ChargingSession).where(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
                ChargingSession.charge_start_at.is_not(None),
            ))).scalars().all())

        for path in images:
            name = os.path.basename(path)
            with open(path, "rb") as fh:
                image = fh.read()
            try:
                ext: Extraction = (await call_openai(image, api_key=openai_key, model=model)).extraction
            except Exception as e:  # noqa: BLE001
                print(f"  {name}: extraction FAILED — {e}")
                continue

            ext_start = _parse_dt(ext.start_at)
            cs = pick_session(candidates, ext_start, ext.soc_start, ext.soc_end, args.time_tolerance_min)
            if cs is None:
                when = ext.start_at or "?"
                print(f"  {name}: no session match (start {when}, soc {ext.soc_start}->{ext.soc_end})")
                continue

            triplets = map_curve_points(ext.power_curve, _curve_secs(cs), cs.start_soc, cs.end_soc)
            if not triplets:
                print(f"  {name} -> #{cs.id}: extraction returned NO usable curve "
                      f"(power_curve={ext.power_curve!r}) — skipped")
                continue

            peak = max(p[2] for p in triplets)
            tag = "" if not cs.power_curve else "  (overwrites existing)"
            print(f"  {name} -> #{cs.id} {cs.date} {cs.start_soc}->{cs.end_soc}% "
                  f"{cs.charging_type}: {len(triplets)} pts, peak {peak:.0f}kW{tag}")
            print(f"      first={triplets[0]}  last={triplets[-1]}")
            if args.apply:
                cs.power_curve = triplets
                written += 1

        if args.apply:
            await session.commit()

    print(f"\n{'Wrote ' + str(written) + ' curve(s).' if args.apply else 'Dry-run only. Re-run with --apply to write.'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill charge curves onto sessions from MyCupra screenshots.")
    p.add_argument("images", nargs="+", help="image file(s) and/or a directory of screenshots")
    p.add_argument("--car-id", type=int, default=None, help="target car id (default: the single active car)")
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run / what-if)")
    p.add_argument("--time-tolerance-min", type=int, default=30,
                   help="max start-time gap (minutes) when matching an image to a session")
    p.add_argument("--database-url", default=None, help="override DATABASE_URL (default: app config)")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
