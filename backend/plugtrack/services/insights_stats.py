# backend/plugtrack/services/insights_stats.py
"""Numeric aggregators for the Insights page.

Lower layer shared by the Insights `/overview` endpoint and the
Telegram usage-chat (`usage_stats`). These return plain numbers — no
formatting, no unit conversion. Every query filters by `user_id`.
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession
from . import mileage_tracking
from .mileage_tracking import KM_PER_MILE
from .session_metrics import drive_cycles


def _base_filter(user_id: int, car_id: Optional[int] = None):
    filters = [ChargingSession.user_id == user_id]
    if car_id is not None:
        filters.append(ChargingSession.car_id == car_id)
    return tuple(filters)


def resolve_granularity(lo: dt.date, hi: dt.date) -> str:
    span = (hi - lo).days
    if span <= 31:
        return "daily"
    if span <= 186:
        return "weekly"
    return "monthly"


def _period_key(d: dt.date, granularity: str) -> str:
    if granularity == "daily":
        return d.isoformat()
    if granularity == "weekly":
        return (d - dt.timedelta(days=d.weekday())).isoformat()
    return d.replace(day=1).isoformat()


def _period_bounds(key: str, granularity: str) -> tuple[dt.date, dt.date]:
    start = dt.date.fromisoformat(key)
    if granularity == "daily":
        return start, start
    if granularity == "weekly":
        return start, start + dt.timedelta(days=6)
    last = calendar.monthrange(start.year, start.month)[1]
    return start, start.replace(day=last)


def _scope(stmt, *, user_id, date_from, date_to, car_id: Optional[int] = None):
    stmt = stmt.where(*_base_filter(user_id, car_id))
    if date_from is not None:
        stmt = stmt.where(ChargingSession.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(ChargingSession.date <= date_to)
    return stmt


async def window_totals(
    session: AsyncSession, *, user_id: int,
    lo: Optional[dt.date], hi: Optional[dt.date],
    car_id: Optional[int] = None,
) -> dict:
    """Single-bucket totals for [lo, hi] (None bounds = open-ended)."""
    costed_kwh = func.sum(
        case((ChargingSession.cost_pence.isnot(None), ChargingSession.kwh_added), else_=0.0)
    )
    stmt = select(
        func.coalesce(func.sum(ChargingSession.cost_pence), 0),
        func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
        func.count(ChargingSession.id),
        func.coalesce(costed_kwh, 0.0),
    ).where(*_base_filter(user_id, car_id))
    if lo is not None:
        stmt = stmt.where(ChargingSession.date >= lo, ChargingSession.date <= hi)
    cost, kwh, n, kwh_costed = (await session.execute(stmt)).one()
    return {
        "spend_pence": int(cost or 0),
        "kwh": float(kwh or 0.0),
        "sessions": int(n or 0),
        "costed_kwh": float(kwh_costed or 0.0),
    }


async def _miles_driven_km(
    session: AsyncSession, *, user_id: int,
    lo: Optional[dt.date], hi: Optional[dt.date],
    car_id: Optional[int] = None,
) -> Optional[float]:
    """Distance driven (km) in [lo, hi], summed across cars (or a single car
    when car_id is supplied), from odometer deltas:
    max(odo <= hi) - max(odo <= lo-1day). Lifetime (lo is None) = max - min.
    Returns None when no car has a computable (bounded) delta."""
    car_id_filter = (
        [ChargingSession.car_id == car_id] if car_id is not None else []
    )
    car_ids = (
        await session.execute(
            select(ChargingSession.car_id)
            .where(*_base_filter(user_id), ChargingSession.odometer_at_session_km.isnot(None),
                   *car_id_filter)
            .distinct()
        )
    ).scalars().all()
    total = 0.0
    any_data = False
    for car_id in car_ids:
        end_stmt = select(func.max(ChargingSession.odometer_at_session_km)).where(
            *_base_filter(user_id),
            ChargingSession.car_id == car_id,
            ChargingSession.odometer_at_session_km.isnot(None),
        )
        if hi is not None:
            end_stmt = end_stmt.where(ChargingSession.date <= hi)
        end = (await session.execute(end_stmt)).scalar_one_or_none()
        if end is None:
            continue
        if lo is None:
            start_stmt = select(func.min(ChargingSession.odometer_at_session_km)).where(
                *_base_filter(user_id),
                ChargingSession.car_id == car_id,
                ChargingSession.odometer_at_session_km.isnot(None),
            )
        else:
            start_stmt = select(func.max(ChargingSession.odometer_at_session_km)).where(
                *_base_filter(user_id),
                ChargingSession.car_id == car_id,
                ChargingSession.odometer_at_session_km.isnot(None),
                ChargingSession.date <= lo - dt.timedelta(days=1),
            )
        start = (await session.execute(start_stmt)).scalar_one_or_none()
        if start is None:
            continue
        delta = float(end) - float(start)
        if delta >= 0:
            total += delta
            any_data = True
    return total if any_data else None


async def spend_energy_over_time(
    session: AsyncSession, *, user_id: int,
    date_from: Optional[dt.date], date_to: Optional[dt.date], granularity: str,
    car_id: Optional[int] = None,
) -> list[dict]:
    stmt = _scope(
        select(ChargingSession.date, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id,
    )
    buckets: dict[str, dict] = {}
    for d, cost, kwh in (await session.execute(stmt)).all():
        key = _period_key(d, granularity)
        b = buckets.setdefault(key, {"spend_pence": 0, "kwh": 0.0, "sessions": 0})
        b["spend_pence"] += int(cost or 0)
        b["kwh"] += float(kwh or 0.0)
        b["sessions"] += 1
    return [
        {"period": k, "spend_pence": buckets[k]["spend_pence"],
         "kwh": round(buckets[k]["kwh"], 3), "sessions": buckets[k]["sessions"]}
        for k in sorted(buckets)
    ]


def _bucket_finalise(b: dict) -> dict:
    avg = round(b["spend_pence"] / b["costed_kwh"], 1) if b["costed_kwh"] > 0 else None
    return {
        "spend_pence": b["spend_pence"], "kwh": round(b["kwh"], 3),
        "sessions": b["sessions"], "avg_p_per_kwh": avg,
    }


async def home_public_split(
    session: AsyncSession, *, user_id: int,
    date_from: Optional[dt.date], date_to: Optional[dt.date],
    car_id: Optional[int] = None,
) -> dict:
    stmt = _scope(
        select(ChargingSession.charging_type, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id,
    )

    def blank():
        return {"spend_pence": 0, "kwh": 0.0, "sessions": 0, "costed_kwh": 0.0}

    agg = {"ac": blank(), "dc": blank()}
    for ctype, cost, kwh in (await session.execute(stmt)).all():
        bucket = "ac" if ctype == "ac" else ("dc" if ctype == "dc" else None)
        if bucket is None:
            continue
        b = agg[bucket]
        b["kwh"] += float(kwh or 0.0)
        b["sessions"] += 1
        if cost is not None:
            b["spend_pence"] += int(cost)
            b["costed_kwh"] += float(kwh or 0.0)
    return {"home": _bucket_finalise(agg["ac"]), "public": _bucket_finalise(agg["dc"])}


async def network_breakdown(
    session: AsyncSession, *, user_id: int,
    date_from: Optional[dt.date], date_to: Optional[dt.date],
    car_id: Optional[int] = None,
) -> list[dict]:
    stmt = _scope(
        select(ChargingSession.charge_network, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to, car_id=car_id,
    )
    _UNKNOWN_VALUES = {"", "unknown", "none", "n/a"}

    agg: dict[str, dict] = {}
    for net, cost, kwh in (await session.execute(stmt)).all():
        stripped = (net or "").strip()
        name = "Unknown" if stripped.lower() in _UNKNOWN_VALUES else stripped
        b = agg.setdefault(name, {"spend_pence": 0, "kwh": 0.0, "sessions": 0, "costed_kwh": 0.0})
        b["kwh"] += float(kwh or 0.0)
        b["sessions"] += 1
        if cost is not None:
            b["spend_pence"] += int(cost)
            b["costed_kwh"] += float(kwh or 0.0)
    rows = [{"network": name, **_bucket_finalise(b)} for name, b in agg.items()]
    rows.sort(key=lambda r: r["spend_pence"], reverse=True)
    return rows


async def efficiency_over_time(
    session: AsyncSession, *, user_id: int,
    date_from: Optional[dt.date], date_to: Optional[dt.date], granularity: str,
    car_id: Optional[int] = None,
) -> list[dict]:
    """Per-period real-world efficiency, de-spiked.

    Each period's `observed_mi_per_kwh` aggregates *drive cycles* whose session
    falls in the period — Σ miles driven ÷ Σ battery energy consumed — instead
    of dividing period miles by period energy *charged* (which spiked/gapped
    because driving and charging don't line up period-to-period).

    `rolling_mi_per_kwh` is the cumulative lifetime efficiency: every cycle up
    to and including the period, so it converges to the car's true mi/kWh.

    `cost_per_mile_p` is the period's charging spend ÷ miles driven that period.
    """
    over = await spend_energy_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to,
        granularity=granularity, car_id=car_id)
    # All cycles across full history (so the rolling lifetime includes data
    # before the window). Each is (date, miles, energy_consumed_kwh).
    cycles = await drive_cycles(session, user_id=user_id, car_id=car_id)

    out: list[dict] = []
    for b in over:
        lo, hi = _period_bounds(b["period"], granularity)
        period_miles = sum(m for (d, m, _e) in cycles if lo <= d <= hi)
        period_energy = sum(e for (d, _m, e) in cycles if lo <= d <= hi)
        cum_miles = sum(m for (d, m, _e) in cycles if d <= hi)
        cum_energy = sum(e for (d, _m, e) in cycles if d <= hi)

        observed = round(period_miles / period_energy, 3) if period_energy > 0 else None
        rolling = round(cum_miles / cum_energy, 3) if cum_energy > 0 else None
        cost_per_mile = (
            round(b["spend_pence"] / period_miles, 2) if period_miles > 0 else None
        )
        out.append({
            "period": b["period"],
            "observed_mi_per_kwh": observed,
            "rolling_mi_per_kwh": rolling,
            "cost_per_mile_p": cost_per_mile,
        })
    return out


def _round_or_none(v: Optional[float], digits: int = 1) -> Optional[float]:
    return None if v is None else round(v, digits)


async def mileage_allowance_view(
    session: AsyncSession, *, user_id: int, car_id: int, today: dt.date,
) -> dict:
    """Per-car annual-allowance view: used/remaining/projected/pace over the
    active tracking period. Ignores any page date filter — the allowance
    period is what matters. Sourced from mileage_tracking.get_status."""
    empty = {
        "enabled": False, "car_id": car_id, "period_start": None, "period_end": None,
        "opening_km": None, "current_km": None, "target_km": None, "used_km": None,
        "remaining_km": None, "days_elapsed": None, "days_total": None,
        "projected_year_end_km": None, "pace": None,
    }
    status = await mileage_tracking.get_status(
        session, user_id=user_id, car_id=car_id, today=today)
    if not status.enabled or status.current_period is None:
        return empty

    cp = status.current_period
    opening = cp.opening_odometer_km
    current = cp.current_odometer_km
    used = max(0.0, current - opening)
    target = cp.annual_mileage_target_km

    days_total = (cp.period_end_date - cp.period_start_date).days + 1
    days_elapsed = (today - cp.period_start_date).days + 1
    days_elapsed = max(0, min(days_elapsed, days_total))

    projected_year_end: Optional[float] = None
    pace: Optional[str] = None
    if days_elapsed > 0:
        projected_used = used / days_elapsed * days_total
        projected_year_end = opening + projected_used
        if target is not None and target > 0:
            if projected_used <= target * 0.98:
                pace = "under"
            elif projected_used >= target * 1.02:
                pace = "over"
            else:
                pace = "on"

    remaining = (target - used) if target is not None else None
    return {
        "enabled": True,
        "car_id": car_id,
        "period_start": cp.period_start_date.isoformat(),
        "period_end": cp.period_end_date.isoformat(),
        "opening_km": _round_or_none(opening),
        "current_km": _round_or_none(current),
        "target_km": _round_or_none(target),
        "used_km": _round_or_none(used),
        "remaining_km": _round_or_none(remaining),
        "days_elapsed": days_elapsed,
        "days_total": days_total,
        "projected_year_end_km": _round_or_none(projected_year_end),
        "pace": pace,
    }
