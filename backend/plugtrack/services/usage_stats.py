# backend/plugtrack/services/usage_stats.py
"""Build a grounded usage-stats snapshot for the Telegram usage-chat feature.

All figures are pre-rendered into display strings (money in £, energy in kWh,
distances in the user's unit) so the answering model performs no arithmetic and
no unit conversion — it only selects and narrates. Every query filters by
user_id.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Setting
from . import mileage_tracking
from .insights_stats import (
    _base_filter,
    _miles_driven_km,
    home_public_split,
    window_totals,
)
from .mileage_tracking import KM_PER_MILE
from .session_metrics import compute_savings_for_sessions, petrol_pence_per_mile


def _gbp(pence: Optional[int]) -> str:
    return f"£{(pence or 0) / 100:,.2f}"


def _kwh(kwh: Optional[float]) -> str:
    return f"{(kwh or 0.0):,.1f} kWh"


def _dist(km: float, unit: str) -> str:
    return f"{km / KM_PER_MILE:,.0f} mi" if unit == "mi" else f"{km:,.0f} km"


def _pkwh(pence_total: Optional[int], kwh_costed: Optional[float]) -> Optional[str]:
    if not kwh_costed or kwh_costed <= 0:
        return None
    return f"{(pence_total or 0) / kwh_costed:,.1f} p/kWh"


def _vs_petrol(pence: Optional[int]) -> Optional[str]:
    """Render a window's net saving vs an equivalent petrol trip."""
    if pence is None:
        return None
    if pence > 0:
        return f"saved {_gbp(pence)} vs petrol"
    if pence < 0:
        return f"{_gbp(-pence)} more than petrol"
    return "about the same as petrol"


@dataclass
class WindowStats:
    label: str
    spend: str
    energy: str
    sessions: int
    avg_p_per_kwh: Optional[str]
    # Actual distance driven in the window, from odometer deltas. None when
    # there isn't enough odometer coverage to bound the window.
    miles_driven: Optional[str] = None
    # Net cost vs an equivalent petrol trip across the window (energy-based,
    # same basis as the per-session UI figure). None when no comparison data.
    vs_petrol: Optional[str] = None


@dataclass
class SplitStats:
    label: str
    home: str
    public: str
    by_network: dict[str, str]


@dataclass
class MileageStats:
    car_label: str
    current: str
    this_year: str
    target: Optional[str]
    pace: Optional[str]


@dataclass
class UsageSnapshot:
    today: str
    distance_unit: str
    # Petrol baseline (e.g. "13.5 p/mile") for the vs-petrol comparisons.
    petrol_p_per_mile: Optional[str] = None
    windows: list[WindowStats] = field(default_factory=list)
    splits: list[SplitStats] = field(default_factory=list)
    mileage: list[MileageStats] = field(default_factory=list)

    def to_prompt_dict(self) -> dict:
        return asdict(self)


def _window_bounds(today: date) -> list[tuple[str, Optional[date], Optional[date]]]:
    first_this = today.replace(day=1)
    last_prev_end = first_this - timedelta(days=1)
    last_prev_start = last_prev_end.replace(day=1)
    return [
        ("this month", first_this, today),
        ("last month", last_prev_start, last_prev_end),
        ("last 30 days", today - timedelta(days=29), today),
        ("last 60 days", today - timedelta(days=59), today),
        ("last 90 days", today - timedelta(days=89), today),
        ("year to date", today.replace(month=1, day=1), today),
        ("lifetime", None, None),
    ]


async def _float_setting(session: AsyncSession, key: str) -> Optional[float]:
    row = (await session.execute(select(Setting.value).where(Setting.key == key))).scalar_one_or_none()
    if row is None or row == "":
        return None
    try:
        return float(row)
    except (TypeError, ValueError):
        return None


async def _petrol_ppm(session: AsyncSession) -> Optional[float]:
    """Petrol pence-per-mile from settings, or None when unset."""
    p = await _float_setting(session, "petrol_price_p_per_litre")
    mpg = await _float_setting(session, "petrol_mpg")
    if p is None or mpg is None:
        return None
    return petrol_pence_per_mile(p, mpg)


async def _petrol_saving_pence(
    session: AsyncSession, *, user_id: int, lo: Optional[date], hi: Optional[date]
) -> Optional[int]:
    """Net saving vs petrol across the window, summing the per-session
    energy-based savings (reuses session_metrics so the figure matches the UI)."""
    stmt = select(ChargingSession).where(*_base_filter(user_id))
    if lo is not None:
        stmt = stmt.where(ChargingSession.date >= lo, ChargingSession.date <= hi)
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return None
    saved = await compute_savings_for_sessions(session, rows)
    vals = [s for (s, _basis, _be) in saved.values() if s is not None]
    if not vals:
        return None
    return int(sum(vals))


async def _window_stats(
    session: AsyncSession, *, user_id: int, label: str,
    lo: Optional[date], hi: Optional[date], unit: str,
) -> WindowStats:
    t = await window_totals(session, user_id=user_id, lo=lo, hi=hi)
    driven_km = await _miles_driven_km(session, user_id=user_id, lo=lo, hi=hi)
    saving = await _petrol_saving_pence(session, user_id=user_id, lo=lo, hi=hi)
    return WindowStats(
        label=label,
        spend=_gbp(t["spend_pence"]),
        energy=_kwh(t["kwh"]),
        sessions=t["sessions"],
        avg_p_per_kwh=_pkwh(t["spend_pence"], t["costed_kwh"]),
        miles_driven=_dist(driven_km, unit) if driven_km is not None else None,
        vs_petrol=_vs_petrol(saving),
    )


def _over(pence: Optional[int], kwh: Optional[float]) -> str:
    return f"{_gbp(int(pence or 0))} over {_kwh(float(kwh or 0.0))}"


async def _split_stats(
    session: AsyncSession, *, user_id: int, label: str,
    lo: Optional[date], hi: Optional[date],
) -> SplitStats:
    def _scoped(stmt):
        stmt = stmt.where(*_base_filter(user_id))
        if lo is not None:
            stmt = stmt.where(ChargingSession.date >= lo, ChargingSession.date <= hi)
        return stmt

    split = await home_public_split(session, user_id=user_id, date_from=lo, date_to=hi)
    home_p, home_k = split["home"]["spend_pence"], split["home"]["kwh"]
    pub_p, pub_k = split["public"]["spend_pence"], split["public"]["kwh"]

    net_stmt = _scoped(
        select(
            ChargingSession.charge_network,
            func.coalesce(func.sum(ChargingSession.cost_pence), 0),
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
        )
        .where(ChargingSession.charging_type == "dc",
               ChargingSession.charge_network.isnot(None))
        .group_by(ChargingSession.charge_network)
    )
    by_network: dict[str, str] = {}
    for net, cost, kwh in (await session.execute(net_stmt)).all():
        by_network[str(net)] = _over(cost, kwh)

    return SplitStats(
        label=label,
        home=_over(home_p, home_k),
        public=_over(pub_p, pub_k),
        by_network=by_network,
    )


async def _mileage_stats(
    session: AsyncSession, *, user_id: int, today: date, distance_unit: str
) -> list[MileageStats]:
    cars = (
        await session.execute(
            select(Car).where(Car.user_id == user_id, Car.active == True)  # noqa: E712
        )
    ).scalars().all()
    out: list[MileageStats] = []
    for car in cars:
        status = await mileage_tracking.get_status(
            session, user_id=user_id, car_id=car.id, today=today
        )
        cp = status.current_period
        if cp is None:
            continue
        this_year_km = max(0.0, cp.current_odometer_km - cp.opening_odometer_km)
        days = (today - cp.period_start_date).days
        pace: Optional[str] = None
        if days > 0:
            annual_km = this_year_km / days * 365
            pace = f"on pace for {_dist(annual_km, distance_unit)}"
        target: Optional[str] = None
        if cp.annual_mileage_target_km is not None:
            target = f"{_dist(cp.annual_mileage_target_km, distance_unit)}/yr target"
        out.append(MileageStats(
            car_label=f"{car.make} {car.model}".strip(),
            current=_dist(cp.current_odometer_km, distance_unit),
            this_year=f"{_dist(this_year_km, distance_unit)} this tracking year",
            target=target,
            pace=pace,
        ))
    return out


async def build_usage_snapshot(
    session: AsyncSession, *, user_id: int, today: date, distance_unit: str
) -> UsageSnapshot:
    snap = UsageSnapshot(today=today.isoformat(), distance_unit=distance_unit)
    ppm = await _petrol_ppm(session)
    snap.petrol_p_per_mile = f"{ppm:,.1f} p/mile" if ppm is not None else None
    for label, lo, hi in _window_bounds(today):
        snap.windows.append(
            await _window_stats(
                session, user_id=user_id, label=label, lo=lo, hi=hi, unit=distance_unit
            )
        )
    bounds = {label: (lo, hi) for label, lo, hi in _window_bounds(today)}
    for label in ("this month", "lifetime"):
        lo, hi = bounds[label]
        snap.splits.append(
            await _split_stats(session, user_id=user_id, label=label, lo=lo, hi=hi)
        )
    snap.mileage = await _mileage_stats(
        session, user_id=user_id, today=today, distance_unit=distance_unit
    )
    return snap
