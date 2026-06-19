# backend/plugtrack/services/insights_stats.py
"""Numeric aggregators for the Insights page.

Lower layer shared by the Insights `/overview` endpoint and the
Telegram usage-chat (`usage_stats`). These return plain numbers — no
formatting, no unit conversion. Every query filters by `user_id` and
excludes `source == "unconfirmed"`.
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

EXCLUDED_SOURCE = "unconfirmed"


def _base_filter(user_id: int):
    return (
        ChargingSession.user_id == user_id,
        ChargingSession.source != EXCLUDED_SOURCE,
    )


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


def _scope(stmt, *, user_id, date_from, date_to):
    stmt = stmt.where(*_base_filter(user_id))
    if date_from is not None:
        stmt = stmt.where(ChargingSession.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(ChargingSession.date <= date_to)
    return stmt


async def window_totals(
    session: AsyncSession, *, user_id: int,
    lo: Optional[dt.date], hi: Optional[dt.date],
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
    ).where(*_base_filter(user_id))
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
) -> Optional[float]:
    """Distance driven (km) in [lo, hi], summed across cars, from odometer
    deltas: max(odo <= hi) - max(odo <= lo-1day). Lifetime (lo is None) =
    max - min. Returns None when no car has a computable (bounded) delta."""
    car_ids = (
        await session.execute(
            select(ChargingSession.car_id)
            .where(*_base_filter(user_id), ChargingSession.odometer_at_session_km.isnot(None))
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
) -> list[dict]:
    stmt = _scope(
        select(ChargingSession.date, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to,
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
) -> dict:
    stmt = _scope(
        select(ChargingSession.charging_type, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to,
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
) -> list[dict]:
    stmt = _scope(
        select(ChargingSession.charge_network, ChargingSession.cost_pence, ChargingSession.kwh_added),
        user_id=user_id, date_from=date_from, date_to=date_to,
    )
    agg: dict[str, dict] = {}
    for net, cost, kwh in (await session.execute(stmt)).all():
        name = net if net else "Unknown"
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
) -> list[dict]:
    over = await spend_energy_over_time(
        session, user_id=user_id, date_from=date_from, date_to=date_to, granularity=granularity)
    out: list[dict] = []
    for b in over:
        lo, hi = _period_bounds(b["period"], granularity)
        driven_km = await _miles_driven_km(session, user_id=user_id, lo=lo, hi=hi)
        observed = cost_per_mile = None
        if driven_km is not None and driven_km > 0 and b["kwh"] > 0:
            miles = driven_km / KM_PER_MILE
            observed = round(miles / b["kwh"], 3)
            cost_per_mile = round(b["spend_pence"] / miles, 2)
        out.append({
            "period": b["period"],
            "observed_mi_per_kwh": observed,
            "cost_per_mile_p": cost_per_mile,
        })
    return out
