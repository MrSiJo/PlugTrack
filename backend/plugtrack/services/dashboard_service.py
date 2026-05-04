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
from datetime import date as date_cls, datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Location


@dataclass
class CarPanel:
    id: int
    make: str
    model: str
    battery_level: Optional[int]
    charging_cable_connected: bool
    last_connected: Optional[datetime]
    next_poll_at: Optional[datetime]
    last_state: Optional[str]
    last_soc: Optional[int]
    active_job_id: Optional[str]
    location_name: Optional[str] = None
    location_address: Optional[str] = None
    # Live telemetry — only meaningful while CHARGING (power/rate) or any
    # state where the car has reported range. Frontend hides nulls.
    electric_range_km: Optional[int] = None
    charging_power_kw: Optional[float] = None
    target_soc: Optional[int] = None
    nominal_efficiency_mi_per_kwh: Optional[float] = None


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
    visit_count: int
    total_kwh: float
    total_cost_pence: int


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def dashboard_summary(
    session: AsyncSession,
    user_id: int,
    orchestrator: Any | None = None,
) -> DashboardSummary:
    """Build a DashboardSummary for the given user.

    `orchestrator`, when supplied, is a `SyncOrchestrator` whose
    `get_state(car_id)` returns the in-memory `CarSyncState`. We merge
    its live fields into each car panel; otherwise we fall back to the
    most-recent session's `end_soc`.
    """
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
        # Defaults from last session, overridden by live orchestrator state.
        battery_level: Optional[int] = last_cs.end_soc if last_cs else None
        last_connected: Optional[datetime] = (
            last_cs.charge_end_at or last_cs.charge_start_at if last_cs else None
        )
        last_state: Optional[str] = None
        last_soc: Optional[int] = battery_level
        next_poll_at: Optional[datetime] = None
        active_job_id: Optional[str] = None
        location_id: Optional[int] = None
        electric_range_km: Optional[int] = None
        charging_power_kw: Optional[float] = None
        target_soc: Optional[int] = None

        if orchestrator is not None:
            try:
                live = orchestrator.get_state(car.id)
            except Exception:  # noqa: BLE001 — defensive
                live = None
            if live is not None:
                if live.last_soc is not None:
                    battery_level = live.last_soc
                    last_soc = live.last_soc
                if live.last_car_captured_timestamp is not None:
                    last_connected = live.last_car_captured_timestamp
                last_state = live.last_state
                next_poll_at = live.next_poll_at
                active_job_id = live.active_job_id
                location_id = getattr(live, "last_location_id", None)
                electric_range_km = getattr(live, "last_electric_range_km", None)
                charging_power_kw = getattr(live, "last_charging_power_kw", None)
                target_soc = getattr(live, "last_target_soc", None)

        # `charging_cable_connected` is derived from the in-memory state
        # machine: PLUGGED_IN, CHARGING, CHARGING_DONE all imply cable in.
        cable_connected = last_state in {"PLUGGED_IN", "CHARGING", "CHARGING_DONE"}

        # Resolve current cluster → name + address.
        location_name: Optional[str] = None
        location_address: Optional[str] = None
        if location_id is not None:
            loc_row = await session.get(Location, location_id)
            if loc_row is not None:
                location_name = loc_row.name
                location_address = loc_row.address

        summary.cars.append(
            CarPanel(
                id=car.id,
                make=car.make,
                model=car.model,
                battery_level=battery_level,
                charging_cable_connected=cable_connected,
                last_connected=last_connected,
                next_poll_at=next_poll_at,
                last_state=last_state,
                last_soc=last_soc,
                active_job_id=active_job_id,
                location_name=location_name,
                location_address=location_address,
                electric_range_km=electric_range_km,
                charging_power_kw=charging_power_kw,
                target_soc=target_soc,
                nominal_efficiency_mi_per_kwh=car.nominal_efficiency_mi_per_kwh,
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
    ).where(ChargingSession.user_id == user_id)
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

    # ---- Top 5 locations (by visit_count) ----
    loc_stmt = (
        select(
            Location.id,
            Location.name,
            Location.visit_count,
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
            func.coalesce(func.sum(ChargingSession.cost_pence), 0),
        )
        .join(
            ChargingSession,
            ChargingSession.location_id == Location.id,
            isouter=True,
        )
        .where(Location.user_id == user_id)
        .group_by(Location.id, Location.name, Location.visit_count)
        .order_by(Location.visit_count.desc(), Location.id.asc())
        .limit(5)
    )
    for loc_id, name, visit_count, kwh, cost in (
        await session.execute(loc_stmt)
    ).all():
        summary.top_locations.append(
            LocationStat(
                id=int(loc_id),
                name=name,
                visit_count=int(visit_count or 0),
                total_kwh=float(kwh or 0.0),
                total_cost_pence=int(cost or 0),
            )
        )

    return summary
