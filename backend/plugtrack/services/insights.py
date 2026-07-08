"""By-location insights aggregation.

Pure aggregation over a user's charging sessions, grouped by location.
Extracted from the route so the avg-p/kWh + pct-of-spend rules are unit-
testable in isolation. See spec 02 §1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession, Location


@dataclass
class LocationBreakdownRow:
    location_id: int | None
    name: str | None
    is_home: bool
    is_free: bool
    spend_pence: int
    kwh: float
    sessions: int
    avg_p_per_kwh: float | None
    first_at: str | None
    last_at: str | None
    pct_of_spend: float


@dataclass
class InsightsByLocation:
    rows: list[LocationBreakdownRow]
    totals: dict


async def aggregate_by_location(
    session: AsyncSession,
    *,
    user_id: int,
    date_from: date_cls | None,
    date_to: date_cls | None,
    car_id: int | None = None,
) -> InsightsByLocation:
    """Aggregate spend/kWh/sessions per location for one user in a window.

    - avg_p_per_kwh excludes unknown-cost sessions (cost_pence IS NULL) from
      both numerator and denominator; None when no costed kWh.
    - pct_of_spend is each group's share of total in-window spend (1dp).
    - Untagged sessions (location_id NULL) roll into an "Unassigned" row,
      included only when it has sessions.
    - Labelled locations with zero in-window sessions are still listed (zeros).
    - Optional car_id restricts aggregation to a single vehicle.
    """
    costed = ChargingSession.cost_pence.isnot(None)
    agg_stmt = (
        select(
            ChargingSession.location_id.label("location_id"),
            func.count(ChargingSession.id).label("sessions"),
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0).label("kwh"),
            func.coalesce(func.sum(case((costed, ChargingSession.cost_pence), else_=0)), 0).label(
                "spend_pence"
            ),
            func.coalesce(
                func.sum(case((costed, ChargingSession.kwh_added), else_=0.0)), 0.0
            ).label("costed_kwh"),
            func.min(ChargingSession.date).label("first_at"),
            func.max(ChargingSession.date).label("last_at"),
        )
        .where(ChargingSession.user_id == user_id)
        .group_by(ChargingSession.location_id)
    )
    if car_id is not None:
        agg_stmt = agg_stmt.where(ChargingSession.car_id == car_id)
    if date_from is not None:
        agg_stmt = agg_stmt.where(ChargingSession.date >= date_from)
    if date_to is not None:
        agg_stmt = agg_stmt.where(ChargingSession.date <= date_to)

    agg_rows = (await session.execute(agg_stmt)).all()
    agg_by_id = {r.location_id: r for r in agg_rows}

    locations = (
        (await session.execute(select(Location).where(Location.user_id == user_id))).scalars().all()
    )

    total_spend = sum(int(r.spend_pence) for r in agg_rows)

    def _pct(spend: int) -> float:
        return round(spend / total_spend * 100, 1) if total_spend > 0 else 0.0

    def _avg(spend: int, costed_kwh: float) -> float | None:
        return round(spend / costed_kwh, 2) if costed_kwh > 0 else None

    def _iso(d) -> str | None:
        return d.isoformat() if d is not None else None

    rows: list[LocationBreakdownRow] = []

    # One row per labelled location (zeros when no in-window sessions).
    for loc in locations:
        agg = agg_by_id.get(loc.id)
        spend = int(agg.spend_pence) if agg is not None else 0
        kwh = float(agg.kwh) if agg is not None else 0.0
        costed_kwh = float(agg.costed_kwh) if agg is not None else 0.0
        rows.append(
            LocationBreakdownRow(
                location_id=loc.id,
                name=loc.name,
                is_home=loc.is_home,
                is_free=loc.is_free,
                spend_pence=spend,
                kwh=kwh,
                sessions=int(agg.sessions) if agg is not None else 0,
                avg_p_per_kwh=_avg(spend, costed_kwh),
                first_at=_iso(agg.first_at) if agg is not None else None,
                last_at=_iso(agg.last_at) if agg is not None else None,
                pct_of_spend=_pct(spend),
            )
        )

    # Unassigned roll-up (untagged sessions in-window), only when present.
    unassigned = agg_by_id.get(None)
    if unassigned is not None:
        spend = int(unassigned.spend_pence)
        rows.append(
            LocationBreakdownRow(
                location_id=None,
                name=None,
                is_home=False,
                is_free=False,
                spend_pence=spend,
                kwh=float(unassigned.kwh),
                sessions=int(unassigned.sessions),
                avg_p_per_kwh=_avg(spend, float(unassigned.costed_kwh)),
                first_at=_iso(unassigned.first_at),
                last_at=_iso(unassigned.last_at),
                pct_of_spend=_pct(spend),
            )
        )

    totals = {
        "spend_pence": total_spend,
        "kwh": round(sum(r.kwh for r in rows), 3),
        "sessions": sum(r.sessions for r in rows),
    }
    return InsightsByLocation(rows=rows, totals=totals)
