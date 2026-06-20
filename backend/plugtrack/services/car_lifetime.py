"""Per-car lifetime statistics aggregator."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession
from .insights_stats import (
    home_public_split,
    window_totals,
    _miles_driven_km,
    KM_PER_MILE,
)


async def compute_car_lifetime(
    session: AsyncSession, *, user_id: int, car_id: int
) -> dict:
    """Compute lifetime statistics for a single car.

    Returned keys:
        ownership_span: {first: ISO date | None, last: ISO date | None}
        total_sessions: int
        total_kwh: float
        total_cost_pence: int
        lifetime_avg_p_per_kwh: float | None  (spend_pence / costed_kwh, None if no costed kWh)
        lifetime_mi_per_kwh: float | None (total miles / total kwh, None if no odometer data or no kwh)
        home_public: {home: {...}, public: {...}}  (from home_public_split)
    """
    # ownership span — min/max date for this car's sessions
    span_stmt = select(
        func.min(ChargingSession.date).label("first"),
        func.max(ChargingSession.date).label("last"),
    ).where(
        ChargingSession.user_id == user_id,
        ChargingSession.car_id == car_id,
    )
    span_row = (await session.execute(span_stmt)).one()
    first_date = span_row.first
    last_date = span_row.last
    ownership_span = {
        "first": first_date.isoformat() if first_date is not None else None,
        "last": last_date.isoformat() if last_date is not None else None,
    }

    # totals — reuse window_totals with no date bounds
    totals = await window_totals(
        session, user_id=user_id, lo=None, hi=None, car_id=car_id
    )
    total_sessions = totals["sessions"]
    total_kwh = totals["kwh"]
    total_cost_pence = totals["spend_pence"]
    costed_kwh = totals["costed_kwh"]

    lifetime_avg_p_per_kwh: Optional[float] = None
    if costed_kwh > 0:
        lifetime_avg_p_per_kwh = round(total_cost_pence / costed_kwh, 2)

    # lifetime mi/kWh — use _miles_driven_km with car_id, no date bounds
    driven_km = await _miles_driven_km(
        session, user_id=user_id, lo=None, hi=None, car_id=car_id
    )
    lifetime_mi_per_kwh: Optional[float] = None
    if driven_km is not None and driven_km > 0 and total_kwh > 0:
        total_miles = driven_km / KM_PER_MILE
        lifetime_mi_per_kwh = round(total_miles / total_kwh, 3)

    # home/public split
    home_public = await home_public_split(
        session, user_id=user_id, date_from=None, date_to=None, car_id=car_id
    )

    return {
        "ownership_span": ownership_span,
        "total_sessions": total_sessions,
        "total_kwh": total_kwh,
        "total_cost_pence": total_cost_pence,
        "lifetime_avg_p_per_kwh": lifetime_avg_p_per_kwh,
        "lifetime_mi_per_kwh": lifetime_mi_per_kwh,
        "home_public": home_public,
    }
