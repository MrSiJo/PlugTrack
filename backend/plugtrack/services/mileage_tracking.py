"""Annual mileage tracking — service layer.

A user enables tracking on a car by entering a start date + opening
odometer (in miles). We persist a `CarMileageYear` row per 12-month
period; the active row has `closing_odometer_km` NULL.

Anniversaries roll over lazily: every read goes through
`get_status`, which materialises any periods whose `period_end_date`
has passed before returning. Closing odometers come from
`ChargingSession.odometer_at_session_km` (max odo at-or-before the
period end), so we never need a scheduled job — accuracy is bounded
by sync recency, not job recency.

Distances are stored in km. The miles ↔ km conversion happens in this
module since the user faces a miles-only form.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CarMileageYear, ChargingSession

# Re-exported for existing importers; defined once in formatting (PLUG-L4).
from .formatting import KM_PER_MILE  # noqa: E402


def miles_to_km(miles: float) -> float:
    return miles * KM_PER_MILE


@dataclass
class MileagePeriod:
    period_start_date: date
    period_end_date: date
    opening_odometer_km: float
    closing_odometer_km: float | None
    annual_mileage_target_km: float | None


@dataclass
class CurrentMileagePeriod:
    period_start_date: date
    period_end_date: date
    opening_odometer_km: float
    # Live max-odometer at-or-before today. Always >= opening.
    current_odometer_km: float
    annual_mileage_target_km: float | None


@dataclass
class MileageStatus:
    enabled: bool
    current_period: CurrentMileagePeriod | None
    history: list[MileagePeriod]


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    # Feb 29 in a non-leap target year → Feb 28.
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def period_end_for(start: date) -> date:
    return _add_year(start) - timedelta(days=1)


async def max_odo_at_or_before(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    on_or_before: date,
) -> float | None:
    stmt = select(func.max(ChargingSession.odometer_at_session_km)).where(
        ChargingSession.user_id == user_id,
        ChargingSession.car_id == car_id,
        ChargingSession.date <= on_or_before,
        ChargingSession.odometer_at_session_km.isnot(None),
    )
    val = (await session.execute(stmt)).scalar_one_or_none()
    return float(val) if val is not None else None


async def _load_active_row(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
) -> CarMileageYear | None:
    stmt = (
        select(CarMileageYear)
        .where(
            CarMileageYear.user_id == user_id,
            CarMileageYear.car_id == car_id,
            CarMileageYear.closing_odometer_km.is_(None),
        )
        .order_by(CarMileageYear.period_start_date.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _materialise_rollovers(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    today: date,
) -> None:
    """Close out any active period whose anniversary has passed.

    Loops in case multiple years passed without the user opening the
    page (closing_n becomes opening_(n+1)). Idempotent — does nothing
    when the active period is still in-window.
    """
    while True:
        active = await _load_active_row(session, user_id=user_id, car_id=car_id)
        if active is None or active.period_end_date >= today:
            return

        max_odo = await max_odo_at_or_before(
            session,
            user_id=user_id,
            car_id=car_id,
            on_or_before=active.period_end_date,
        )
        # Closing must be >= opening (mileage only goes up). If we have
        # no session data inside the window — or a freak older odo — we
        # close at opening, i.e. zero miles for that period.
        closing = max(active.opening_odometer_km, max_odo or active.opening_odometer_km)
        active.closing_odometer_km = closing

        next_start = active.period_end_date + timedelta(days=1)
        next_row = CarMileageYear(
            user_id=user_id,
            car_id=car_id,
            period_start_date=next_start,
            period_end_date=period_end_for(next_start),
            opening_odometer_km=closing,
            closing_odometer_km=None,
            annual_mileage_target_km=active.annual_mileage_target_km,
        )
        session.add(next_row)
        await session.flush()


async def get_status(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    today: date | None = None,
) -> MileageStatus:
    today = today or date.today()
    await _materialise_rollovers(session, user_id=user_id, car_id=car_id, today=today)

    # Pull every row, ordered newest-first so the active row (if any)
    # comes first.
    stmt = (
        select(CarMileageYear)
        .where(
            CarMileageYear.user_id == user_id,
            CarMileageYear.car_id == car_id,
        )
        .order_by(CarMileageYear.period_start_date.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    if not rows:
        return MileageStatus(enabled=False, current_period=None, history=[])

    # Active row = closing is NULL. There can only be zero or one.
    active = next((r for r in rows if r.closing_odometer_km is None), None)
    history = [
        MileagePeriod(
            period_start_date=r.period_start_date,
            period_end_date=r.period_end_date,
            opening_odometer_km=r.opening_odometer_km,
            closing_odometer_km=r.closing_odometer_km,
            annual_mileage_target_km=r.annual_mileage_target_km,
        )
        for r in rows
        if r.closing_odometer_km is not None
    ]

    current: CurrentMileagePeriod | None = None
    if active is not None:
        max_odo = await max_odo_at_or_before(
            session,
            user_id=user_id,
            car_id=car_id,
            on_or_before=today,
        )
        current_odo = max(
            active.opening_odometer_km,
            max_odo if max_odo is not None else active.opening_odometer_km,
        )
        current = CurrentMileagePeriod(
            period_start_date=active.period_start_date,
            period_end_date=active.period_end_date,
            opening_odometer_km=active.opening_odometer_km,
            current_odometer_km=current_odo,
            annual_mileage_target_km=active.annual_mileage_target_km,
        )

    return MileageStatus(enabled=True, current_period=current, history=history)


async def set_tracking(
    session: AsyncSession,
    *,
    user_id: int,
    car_id: int,
    start_date: date,
    opening_miles: float,
    annual_mileage_target_miles: float | None,
    today: date | None = None,
) -> MileageStatus:
    """Enable or replace mileage tracking for this car.

    Wipes any existing rows (including history) and creates a single
    fresh active row from the supplied baseline. Then materialises any
    rollovers that have already happened so the call returns a fully
    consistent status.
    """
    today = today or date.today()

    await session.execute(
        delete(CarMileageYear).where(
            CarMileageYear.user_id == user_id,
            CarMileageYear.car_id == car_id,
        )
    )

    target_km: float | None = (
        miles_to_km(annual_mileage_target_miles)
        if annual_mileage_target_miles is not None
        else None
    )

    row = CarMileageYear(
        user_id=user_id,
        car_id=car_id,
        period_start_date=start_date,
        period_end_date=period_end_for(start_date),
        opening_odometer_km=miles_to_km(opening_miles),
        closing_odometer_km=None,
        annual_mileage_target_km=target_km,
    )
    session.add(row)
    await session.flush()

    return await get_status(session, user_id=user_id, car_id=car_id, today=today)


async def clear_tracking(session: AsyncSession, *, user_id: int, car_id: int) -> None:
    await session.execute(
        delete(CarMileageYear).where(
            CarMileageYear.user_id == user_id,
            CarMileageYear.car_id == car_id,
        )
    )
