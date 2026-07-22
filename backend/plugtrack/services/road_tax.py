"""eVED (pay-per-mile) road-tax projection.

Indicative estimate of the proposed UK EV pay-per-mile charge (live from
April 2028) plus flat VED, per car. Reuses the annualised mileage engine
in `insights_stats.mileage_allowance_view` — no new mileage window.

All money is in pence. Mileage is always converted km→mi because eVED is
billed per mile regardless of the user's display `distance_unit`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as date_cls

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Setting
from .insights_stats import mileage_allowance_view
from .mileage_tracking import KM_PER_MILE

_LOW_CONFIDENCE_DAYS = 14


@dataclass(frozen=True)
class EvedProjection:
    rate_p_per_mile: float
    running_miles: float
    running_pence: float
    projected_annual_miles: float
    projected_pence: float
    ved_pence: float
    total_due_pence: float
    renewal_date: str
    low_confidence: bool


async def _read_float(session: AsyncSession, key: str, default: float) -> float:
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None or row.value is None:
        return default
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return default


async def _read_str(session: AsyncSession, key: str, default: str) -> str:
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None or row.value is None or row.value == "":
        return default
    return row.value


async def eved_projection(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    today: date_cls | None = None,
) -> EvedProjection | None:
    """Per-car eVED + VED estimate, or None when the car has no active
    mileage-tracking period (or no projection can be formed)."""
    if today is None:
        today = datetime.now(UTC).date()

    view = await mileage_allowance_view(session, user_id=user_id, car_id=car_id, today=today)
    if not view.get("enabled"):
        return None

    opening_km = view.get("opening_km")
    projected_end_km = view.get("projected_year_end_km")
    used_km = view.get("used_km") or 0.0
    days_elapsed = view.get("days_elapsed") or 0
    if opening_km is None or projected_end_km is None:
        return None

    rate = await _read_float(session, "eved_rate_p_per_mile", 3.0)
    ved_gbp = await _read_float(session, "ved_annual_cost_gbp", 200.0)
    renewal_date = await _read_str(session, "ved_renewal_date", "07-31")

    running_miles = max(0.0, used_km) / KM_PER_MILE
    projected_annual_miles = max(0.0, projected_end_km - opening_km) / KM_PER_MILE
    running_pence = running_miles * rate
    projected_pence = projected_annual_miles * rate
    ved_pence = ved_gbp * 100.0

    return EvedProjection(
        rate_p_per_mile=rate,
        running_miles=round(running_miles, 1),
        running_pence=round(running_pence, 2),
        projected_annual_miles=round(projected_annual_miles, 1),
        projected_pence=round(projected_pence, 2),
        ved_pence=round(ved_pence, 2),
        total_due_pence=round(projected_pence + ved_pence, 2),
        renewal_date=renewal_date,
        low_confidence=days_elapsed < _LOW_CONFIDENCE_DAYS,
    )
