# backend/plugtrack/scripts/remap_curves.py
"""CLI to re-map stored screenshot extractions onto existing session curves.

Unlike `backfill_curves`, this makes NO network calls and costs nothing: the
raw `[fraction, kw]` points the vision model returned are already persisted in
`screenshot_import.extracted`, so a curve can be rebuilt purely from data we
hold. That matters because `map_curve_points` used to strip the leading and
trailing zero-power samples — the rising and falling edges of the trace — and
every curve committed before that fix is missing them. Re-mapping restores the
edges without re-reading a single image.

Writes ONLY `power_curve`, never cost / SoC / kWh / rate, so it stays clear of
any cost re-rating. Idempotent: re-running produces the same result.

    docker exec plugtrack-api \\
        python -m plugtrack.scripts.remap_curves            # dry-run
    docker exec plugtrack-api \\
        python -m plugtrack.scripts.remap_curves --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from ..models import ChargingSession, ScreenshotImport
from ..services.screenshot_commit import map_curve_points
from ..services.screenshot_correlation import _parse_dt
from .backfill_curves import _curve_secs, pick_session

# Screenshot start times and session start times are recorded independently, so
# allow the same slack the image-based backfill uses.
_DEFAULT_TOL_MIN = 90


def _extraction_curve(extracted: dict | None) -> list | None:
    """The raw [fraction, kw] points from a stored extraction, if any."""
    if not isinstance(extracted, dict):
        return None
    curve = extracted.get("power_curve")
    return curve if isinstance(curve, list) and curve else None


async def _run(args: argparse.Namespace) -> int:
    if args.database_url:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(args.database_url, future=True)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    else:
        from ..db import SessionLocal as sessionmaker  # configured engine

    changed = skipped = unmatched = 0

    async with sessionmaker() as session:
        imports = list(
            (await session.execute(select(ScreenshotImport).order_by(ScreenshotImport.id)))
            .scalars()
            .all()
        )
        sessions = list((await session.execute(select(ChargingSession))).scalars().all())

        for imp in imports:
            curve = _extraction_curve(imp.extracted)
            if curve is None:
                continue
            ext = imp.extracted or {}

            # Prefer the recorded link; fall back to matching on start time + SoC.
            cs = None
            if imp.created_session_id is not None:
                cs = next((c for c in sessions if c.id == imp.created_session_id), None)
            if cs is None:
                cs = pick_session(
                    [c for c in sessions if c.user_id == imp.user_id],
                    _parse_dt(ext.get("start_at")),
                    ext.get("soc_start"),
                    ext.get("soc_end"),
                    args.tolerance_min,
                )
            if cs is None:
                unmatched += 1
                print(f"import {imp.id}: no matching session — skipped")
                continue

            remapped = map_curve_points(curve, _curve_secs(cs), cs.start_soc, cs.end_soc)
            if remapped is None:
                skipped += 1
                continue
            if remapped == cs.power_curve:
                skipped += 1
                continue

            before = len(cs.power_curve or [])
            print(
                f"import {imp.id} -> session {cs.id}: "
                f"{before} -> {len(remapped)} points" + ("" if args.apply else "  (dry-run)")
            )
            if args.apply:
                cs.power_curve = remapped
            changed += 1

        if args.apply:
            await session.commit()

    verb = "updated" if args.apply else "would update"
    print(f"\n{verb} {changed} session(s); {skipped} unchanged; {unmatched} unmatched")
    if not args.apply and changed:
        print("Re-run with --apply to write.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    p.add_argument(
        "--tolerance-min",
        type=int,
        default=_DEFAULT_TOL_MIN,
        help=f"start-time match tolerance in minutes (default {_DEFAULT_TOL_MIN})",
    )
    p.add_argument("--database-url", default=None, help="override the configured DB URL")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
