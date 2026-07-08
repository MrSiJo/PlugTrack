"""Dashboard aggregation service.

Pulls everything the v1 dashboard panels need in a single AsyncSession:

- Per-car panel snapshot (live state from the orchestrator if available,
  falling back to the most recent ChargingSession's `end_soc`).
- Last 10 charging sessions across all of the user's cars (date desc).
- Lifetime totals (kWh, cost in pence, distance in km, count).
- Top 5 locations by `visit_count` with kWh/cost rollups.

All distance values stay in km — UI converts via `formatDistance` /
`distance_unit`. All cost values stay in integer pence.

Distance is derived as the cumulative `kwh_added * nominal_efficiency`
proxy when no odometer span is available; for v1 we sum the car-level
`max(odometer_at_session_km) - min(odometer_at_session_km)` per car
since odometers are not guaranteed to be present on every row. If a car
has fewer than 2 odometer readings the contribution is 0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Location
from . import mileage_tracking
from .mileage_tracking import KM_PER_MILE
from .usage_stats import miles_driven_km


@dataclass
class MileageYearSummary:
    period_start_date: date_cls
    period_end_date: date_cls
    opening_odometer_km: float
    current_odometer_km: float
    annual_mileage_target_km: Optional[float]


@dataclass
class CarPanel:
    id: int
    make: str
    model: str
    # Snapshot from the most recent session's `end_soc` — there is no live
    # sync subsystem any more (v3.0 pivot), so this is "after last charge".
    battery_level: Optional[int]
    last_connected: Optional[datetime]
    last_soc: Optional[int]
    nominal_efficiency_mi_per_kwh: Optional[float] = None
    # Active annual mileage tracking period — null when the user hasn't
    # enabled tracking on this car. See `services/mileage_tracking.py`.
    mileage_year: Optional[MileageYearSummary] = None


@dataclass
class SessionRow:
    id: int
    car_id: int
    car_label: str
    date: date_cls
    kwh_added: float
    cost_pence: Optional[int]
    cost_basis: str
    location_id: Optional[int]
    location_name: Optional[str]
    charge_network: Optional[str]
    source: str


@dataclass
class LifetimeTotals:
    kwh: float
    cost_pence: int
    distance_km: int
    sessions_count: int


@dataclass
class LocationStat:
    id: int
    name: Optional[str]
    # Number of charging sessions recorded at this location. NOT the
    # Location.visit_count clustering counter — that is only bumped by live
    # plug-in detection and stays 0 for manual / backfilled sessions.
    charge_count: int
    total_kwh: float
    total_cost_pence: int


@dataclass
class CostPerMile:
    # Cost ÷ miles driven, in pence per mile. Null when there isn't enough
    # odometer coverage to bound the window's distance.
    lifetime_pence: Optional[float] = None
    rolling_30d_pence: Optional[float] = None


@dataclass
class DashboardSummary:
    cars: list[CarPanel] = field(default_factory=list)
    recent_sessions: list[SessionRow] = field(default_factory=list)
    lifetime_totals: LifetimeTotals = field(
        default_factory=lambda: LifetimeTotals(
            kwh=0.0, cost_pence=0, distance_km=0, sessions_count=0
        )
    )
    top_locations: list[LocationStat] = field(default_factory=list)
    cost_per_mile: CostPerMile = field(default_factory=CostPerMile)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def dashboard_summary(
    session: AsyncSession,
    user_id: int,
    today: Optional[date_cls] = None,
) -> DashboardSummary:
    """Build a DashboardSummary for the given user.

    The live sync subsystem has been removed, so the per-car panel's
    battery readout falls back to the most-recent session's `end_soc`.

    `today` anchors the rolling 30-day cost-per-mile window; it defaults to
    the current UTC date and is injectable for deterministic tests.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    summary = DashboardSummary()

    # ---- Cars (active only) ----
    cars_result = await session.execute(
        select(Car)
        .where(Car.user_id == user_id, Car.active == True)  # noqa: E712
        .order_by(Car.id)
    )
    cars: list[Car] = list(cars_result.scalars().all())

    # Pre-compute the most recent session per car for the SoC fallback +
    # last_connected column.
    last_session_by_car: dict[int, ChargingSession] = {}
    if cars:
        car_ids = [c.id for c in cars]
        # Subquery: latest session id per car_id (use date, then id as tiebreaker).
        latest_ids_subq = (
            select(
                ChargingSession.car_id,
                func.max(ChargingSession.id).label("max_id"),
            )
            .where(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id.in_(car_ids),
            )
            .group_by(ChargingSession.car_id)
            .subquery()
        )
        latest_rows = await session.execute(
            select(ChargingSession).join(
                latest_ids_subq, ChargingSession.id == latest_ids_subq.c.max_id
            )
        )
        for cs in latest_rows.scalars().all():
            last_session_by_car[cs.car_id] = cs

    for car in cars:
        last_cs = last_session_by_car.get(car.id)
        # The live sync subsystem is gone — battery falls back to the most
        # recent session's `end_soc`.
        battery_level: Optional[int] = last_cs.end_soc if last_cs else None
        last_connected: Optional[datetime] = (
            last_cs.charge_end_at or last_cs.charge_start_at if last_cs else None
        )

        # Mileage tracking — active period only. `get_status` materialises
        # any anniversaries that have rolled over since the last visit;
        # the caller (dashboard route) commits the resulting writes.
        mileage_status = await mileage_tracking.get_status(
            session, user_id=user_id, car_id=car.id
        )
        mileage_year: Optional[MileageYearSummary] = None
        if mileage_status.current_period is not None:
            cp = mileage_status.current_period
            mileage_year = MileageYearSummary(
                period_start_date=cp.period_start_date,
                period_end_date=cp.period_end_date,
                opening_odometer_km=cp.opening_odometer_km,
                current_odometer_km=cp.current_odometer_km,
                annual_mileage_target_km=cp.annual_mileage_target_km,
            )

        summary.cars.append(
            CarPanel(
                id=car.id,
                make=car.make,
                model=car.model,
                battery_level=battery_level,
                last_connected=last_connected,
                last_soc=battery_level,
                nominal_efficiency_mi_per_kwh=car.nominal_efficiency_mi_per_kwh,
                mileage_year=mileage_year,
            )
        )

    # ---- Recent sessions (last 10 across all cars) ----
    car_label_by_id = {c.id: f"{c.make} {c.model}".strip() for c in cars}
    recent_stmt = (
        select(ChargingSession, Location.name)
        .join(Location, ChargingSession.location_id == Location.id, isouter=True)
        .where(ChargingSession.user_id == user_id)
        .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
        .limit(10)
    )
    recent_rows = await session.execute(recent_stmt)
    for cs, loc_name in recent_rows.all():
        summary.recent_sessions.append(
            SessionRow(
                id=cs.id,
                car_id=cs.car_id,
                car_label=car_label_by_id.get(cs.car_id, f"car #{cs.car_id}"),
                date=cs.date,
                kwh_added=cs.kwh_added,
                cost_pence=cs.cost_pence,
                cost_basis=cs.cost_basis,
                location_id=cs.location_id,
                location_name=cs.user_label or loc_name,
                charge_network=cs.charge_network,
                source=cs.source,
            )
        )

    # ---- Lifetime totals ----
    totals_stmt = select(
        func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
        func.coalesce(func.sum(ChargingSession.cost_pence), 0),
        func.count(ChargingSession.id),
    ).where(
        ChargingSession.user_id == user_id,
    )
    kwh_sum, cost_sum, sessions_count = (await session.execute(totals_stmt)).one()

    # Distance proxy: per-car (max - min) odometer span, summed.
    distance_km_total = 0.0
    if cars:
        odo_stmt = (
            select(
                ChargingSession.car_id,
                func.min(ChargingSession.odometer_at_session_km),
                func.max(ChargingSession.odometer_at_session_km),
            )
            .where(
                ChargingSession.user_id == user_id,
                ChargingSession.odometer_at_session_km.isnot(None),
            )
            .group_by(ChargingSession.car_id)
        )
        for _car_id, lo, hi in (await session.execute(odo_stmt)).all():
            if lo is None or hi is None:
                continue
            span = float(hi) - float(lo)
            if span > 0:
                distance_km_total += span

    summary.lifetime_totals = LifetimeTotals(
        kwh=float(kwh_sum or 0.0),
        cost_pence=int(cost_sum or 0),
        distance_km=int(round(distance_km_total)),
        sessions_count=int(sessions_count or 0),
    )

    # ---- Cost per mile (lifetime + rolling 30 days) ----
    # Numerators reuse the cost sums above; denominators come from
    # `miles_driven_km` (the single source of truth for windowed odometer
    # deltas).
    def _ppm(cost_pence: int, miles_km: Optional[float]) -> Optional[float]:
        if not miles_km or miles_km <= 0:
            return None
        return float(cost_pence) / (miles_km / KM_PER_MILE)

    lo_30d = today - timedelta(days=29)
    cost_30d = (
        await session.execute(
            select(func.coalesce(func.sum(ChargingSession.cost_pence), 0)).where(
                ChargingSession.user_id == user_id,
                ChargingSession.date >= lo_30d,
                ChargingSession.date <= today,
            )
        )
    ).scalar_one()
    lifetime_miles_km = await miles_driven_km(
        session, user_id=user_id, lo=None, hi=None
    )
    rolling_miles_km = await miles_driven_km(
        session, user_id=user_id, lo=lo_30d, hi=today
    )
    summary.cost_per_mile = CostPerMile(
        lifetime_pence=_ppm(int(cost_sum or 0), lifetime_miles_km),
        rolling_30d_pence=_ppm(int(cost_30d or 0), rolling_miles_km),
    )

    # ---- Top 5 locations (by number of charging sessions) ----
    # Rank by how many charges happened at each location. Locations with zero
    # charging sessions are excluded (HAVING), so a clustered-but-never-charged
    # spot doesn't show up with a "0 charges / £0" row.
    charge_count_col = func.count(ChargingSession.id)
    loc_stmt = (
        select(
            Location.id,
            Location.name,
            charge_count_col,
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
            func.coalesce(func.sum(ChargingSession.cost_pence), 0),
        )
        .join(
            ChargingSession,
            ChargingSession.location_id == Location.id,
            isouter=True,
        )
        .where(Location.user_id == user_id)
        .group_by(Location.id, Location.name)
        .having(charge_count_col > 0)
        .order_by(charge_count_col.desc(), Location.id.asc())
        .limit(5)
    )
    for loc_id, name, n_charges, kwh, cost in (
        await session.execute(loc_stmt)
    ).all():
        summary.top_locations.append(
            LocationStat(
                id=int(loc_id),
                name=name,
                charge_count=int(n_charges or 0),
                total_kwh=float(kwh or 0.0),
                total_cost_pence=int(cost or 0),
            )
        )

    return summary
