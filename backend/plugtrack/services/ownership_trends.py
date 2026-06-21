# backend/plugtrack/services/ownership_trends.py
"""Ownership-trends aggregators (Task 1).

Pure read-time aggregators; no schema changes. All functions filter by
(user_id, car_id) — never cross-user or cross-car leakage.

UNITS
-----
mi_per_kwh      — MILES-based (consistent with insights_stats.efficiency_over_time
                  which exposes observed_mi_per_kwh).
derived_range_km — km (= mi_per_kwh × battery_kwh × KM_PER_MILE).
                  The frontend's formatDistance() converts for display per
                  the user's distance_unit preference.

SEASON MAPPING (documented; used conceptually — seasonal_delta keeps it simple)
----
  winter = Dec, Jan, Feb
  spring = Mar, Apr, May
  summer = Jun, Jul, Aug
  autumn = Sep, Oct, Nov

seasonal_delta does NOT require data in different labelled seasons; it simply
returns the best vs worst month once ≥2 non-None mi_per_kwh data points exist
in *different calendar month strings* (period). This is the simplest correct
behaviour that serves the seasonal-range interpretation.

QUALIFYING CHARGE THRESHOLD
----
For capacity_trend / current_estimated_capacity a charge qualifies when:
  - kwh_added > 0
  - start_soc and end_soc are both valid (non-null — model guarantees int)
  - (end_soc - start_soc) >= 40  (percentage-point delta; 40 pp chosen to
    exclude partial top-ups that overstate per-kWh usable capacity)

LOW_CONFIDENCE for capacity_trend
----
A point is low_confidence=True when:
  - The charge was AC (AC charging losses make usable_kwh an overestimate), OR
  - Total qualifying charges for this car is fewer than 3 (not enough data).

CURRENT_ESTIMATED_CAPACITY smoothing (N=10)
----
Rolling median of the most recent N=10 qualifying charges.
DC preference: when ≥3 DC qualifying charges exist, use ONLY the DC subset
(DC is less affected by charging losses than AC). Falls back to all qualifying
when fewer than 3 DC charges qualify.
"""
from __future__ import annotations

import calendar
import datetime as dt
import statistics
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession
from .mileage_tracking import KM_PER_MILE
from .session_metrics import drive_cycles

# Rolling-median window for current_estimated_capacity
_CAPACITY_N = 10

# Minimum qualifying delta (percentage points) for capacity inference
_MIN_SOC_DELTA = 40

# Minimum qualifying charges for a DC-preferred set
_DC_PREFER_THRESHOLD = 3

# Minimum total qualifying charges before low_confidence=False
_MIN_QUALIFYING = 3


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Return (first, last) date for the given year/month."""
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def _month_key(d: dt.date) -> str:
    """Return 'YYYY-MM' string for a date."""
    return d.strftime("%Y-%m")


async def _distinct_months(
    session: AsyncSession, *, user_id: int, car_id: int,
) -> list[tuple[int, int]]:
    """Return sorted list of (year, month) tuples with ≥1 session."""
    stmt = (
        select(ChargingSession.date)
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
        )
        .order_by(ChargingSession.date)
    )
    rows = (await session.execute(stmt)).scalars().all()
    seen: dict[tuple[int, int], None] = {}
    for d in rows:
        key = (d.year, d.month)
        seen[key] = None
    return list(seen.keys())


async def _session_count_in_month(
    session: AsyncSession, *, user_id: int, car_id: int, lo: dt.date, hi: dt.date
) -> int:
    stmt = (
        select(func.count(ChargingSession.id))
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
            ChargingSession.date >= lo,
            ChargingSession.date <= hi,
        )
    )
    return (await session.execute(stmt)).scalar_one() or 0


async def efficiency_by_month(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    battery_kwh: float,
) -> list[dict]:
    """Monthly efficiency points for a single car.

    Returns time-ordered list of dicts:
      {
        "period": "YYYY-MM",
        "mi_per_kwh": float | None,
        "derived_range_km": float | None,
        "low_confidence": bool,
      }

    Only emits months that have at least one session. Per-car scoped.

    mi/kWh = (driven_km / KM_PER_MILE) / month_kwh
    derived_range_km = mi_per_kwh × battery_kwh × KM_PER_MILE
    low_confidence = True when sessions < 2 OR driven_km is None.
    """
    months = await _distinct_months(session, user_id=user_id, car_id=car_id)
    if not months:
        return []

    # Drive cycles (miles, consumed kWh) for this car — aggregated per month so
    # mi/kWh is consistent with the de-spiked efficiency-over-time chart rather
    # than dividing month miles by month energy charged.
    cycles = await drive_cycles(session, user_id=user_id, car_id=car_id)

    out: list[dict] = []
    for year, month in months:
        lo, hi = _month_bounds(year, month)
        period = _month_key(lo)

        n_sessions = await _session_count_in_month(
            session, user_id=user_id, car_id=car_id, lo=lo, hi=hi
        )

        month_miles = sum(m for (d, m, _e) in cycles if lo <= d <= hi)
        month_energy = sum(e for (d, _m, e) in cycles if lo <= d <= hi)

        mi_per_kwh: Optional[float] = None
        derived_range_km: Optional[float] = None

        if month_miles > 0 and month_energy > 0:
            mi_per_kwh = month_miles / month_energy
            derived_range_km = mi_per_kwh * battery_kwh * KM_PER_MILE

        low_confidence = n_sessions < 2 or mi_per_kwh is None

        out.append(
            {
                "period": period,
                "mi_per_kwh": mi_per_kwh,
                "derived_range_km": derived_range_km,
                "low_confidence": low_confidence,
            }
        )

    return out


def seasonal_delta(points: list[dict]) -> Optional[dict]:
    """Best vs worst month comparison from efficiency_by_month output.

    Requires ≥2 data points with non-None mi_per_kwh in *different calendar
    month keys* (different "period" strings). Returns None otherwise.

    The conceptual interpretation is seasonal (summer efficiency tends to exceed
    winter due to battery temperature), but we make no hard season-labelling
    requirement — best vs worst month is the simplest statistically sound result.

    Returns:
      {
        "best": <point dict>,
        "worst": <point dict>,
        "pct": float,       # (best - worst) / worst * 100
        "abs_mi_per_kwh": float,  # best - worst
      }
    """
    valid = [p for p in points if p.get("mi_per_kwh") is not None]
    if len(valid) < 2:
        return None

    # Check they're in different periods (different YYYY-MM strings)
    if len({p["period"] for p in valid}) < 2:
        return None

    best = max(valid, key=lambda p: p["mi_per_kwh"])
    worst = min(valid, key=lambda p: p["mi_per_kwh"])

    if worst["mi_per_kwh"] == 0:
        return None

    pct = (best["mi_per_kwh"] - worst["mi_per_kwh"]) / worst["mi_per_kwh"] * 100
    abs_mi = best["mi_per_kwh"] - worst["mi_per_kwh"]

    return {
        "best": best,
        "worst": worst,
        "pct": round(pct, 2),
        "abs_mi_per_kwh": round(abs_mi, 4),
    }


async def _qualifying_charges(
    session: AsyncSession, *, user_id: int, car_id: int
) -> list[dict]:
    """Fetch all qualifying charges for capacity inference, ordered by date asc.

    Qualifying = kwh_added > 0 AND (end_soc - start_soc) >= _MIN_SOC_DELTA.
    Returns list of dicts with keys: date, usable_kwh, charging_type.
    """
    stmt = (
        select(
            ChargingSession.date,
            ChargingSession.kwh_added,
            ChargingSession.start_soc,
            ChargingSession.end_soc,
            ChargingSession.charging_type,
        )
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
            ChargingSession.kwh_added > 0,
        )
        .order_by(ChargingSession.date, ChargingSession.id)
    )
    rows = (await session.execute(stmt)).all()

    result = []
    for d, kwh, s_soc, e_soc, ctype in rows:
        delta = (e_soc or 0) - (s_soc or 0)
        if delta < _MIN_SOC_DELTA:
            continue
        usable_kwh = round(float(kwh) / (delta / 100.0), 2)
        result.append(
            {
                "date": d.isoformat(),
                "usable_kwh": usable_kwh,
                "charging_type": ctype,
            }
        )

    return result


async def capacity_trend(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    battery_kwh: float,
) -> list[dict]:
    """Time-ordered capacity-inference points from qualifying charges.

    Qualifying = kwh_added > 0 AND (end_soc - start_soc) >= 40 pp.

    Per charge:
      usable_kwh = kwh_added / ((end_soc - start_soc) / 100)

    low_confidence = True when:
      - charging_type == "ac" (AC losses overstate usable capacity), OR
      - total qualifying charges for this car < 3 (too few data points)

    Returns time-ordered (ascending date) list of:
      {
        "date": "YYYY-MM-DD",
        "usable_kwh": float (rounded to 2dp),
        "charging_type": "ac" | "dc" | "unknown",
        "low_confidence": bool,
      }
    """
    qualifying = await _qualifying_charges(session, user_id=user_id, car_id=car_id)
    total = len(qualifying)
    sparse = total < _MIN_QUALIFYING

    out = []
    for pt in qualifying:
        is_ac = pt["charging_type"] == "ac"
        lc = is_ac or sparse
        out.append(
            {
                "date": pt["date"],
                "usable_kwh": pt["usable_kwh"],
                "charging_type": pt["charging_type"],
                "low_confidence": lc,
            }
        )

    return out


async def current_estimated_capacity(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    battery_kwh: float,
) -> Optional[float]:
    """Rolling median of the most recent N=10 qualifying charges' usable_kwh.

    DC preference: when ≥3 DC qualifying charges exist, use ONLY the most
    recent N DC charges (less affected by charging losses). Falls back to all
    qualifying (AC + DC + unknown) when fewer than 3 DC charges qualify.

    Returns None when no qualifying charges exist.

    N = 10 (module constant _CAPACITY_N).
    DC-prefer threshold = 3 (module constant _DC_PREFER_THRESHOLD).
    """
    qualifying = await _qualifying_charges(session, user_id=user_id, car_id=car_id)
    if not qualifying:
        return None

    # Most-recent-first for window selection
    by_date_desc = list(reversed(qualifying))

    dc_qualifying = [p for p in by_date_desc if p["charging_type"] == "dc"]

    if len(dc_qualifying) >= _DC_PREFER_THRESHOLD:
        pool = dc_qualifying[:_CAPACITY_N]
    else:
        pool = by_date_desc[:_CAPACITY_N]

    values = [p["usable_kwh"] for p in pool]
    return statistics.median(values)


async def seasonal_range_span(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    battery_kwh: float,
) -> Optional[dict]:
    """Min/max/avg derived_range_km across months with non-None range.

    Delegates to efficiency_by_month; aggregates the derived_range_km field.
    Returns None when no months have a computable range.

    Returns:
      {
        "min_km": float,
        "max_km": float,
        "avg_km": float,
      }
    """
    pts = await efficiency_by_month(
        session, user_id=user_id, car_id=car_id, battery_kwh=battery_kwh
    )

    ranges = [
        p["derived_range_km"]
        for p in pts
        if p.get("derived_range_km") is not None
    ]

    if not ranges:
        return None

    return {
        "min_km": min(ranges),
        "max_km": max(ranges),
        "avg_km": sum(ranges) / len(ranges),
    }
