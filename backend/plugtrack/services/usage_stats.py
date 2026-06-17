# backend/plugtrack/services/usage_stats.py
"""Build a grounded usage-stats snapshot for the Telegram usage-chat feature.

All figures are pre-rendered into display strings (money in £, energy in kWh,
distances in the user's unit) so the answering model performs no arithmetic and
no unit conversion — it only selects and narrates. Every query filters by
user_id and excludes `source == "unconfirmed"`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession
from .mileage_tracking import KM_PER_MILE


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


@dataclass
class WindowStats:
    label: str
    spend: str
    energy: str
    sessions: int
    avg_p_per_kwh: Optional[str]


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
        ("year to date", today.replace(month=1, day=1), today),
        ("lifetime", None, None),
    ]


def _base_filter(user_id: int):
    return (
        ChargingSession.user_id == user_id,
        ChargingSession.source != "unconfirmed",
    )


async def _window_stats(
    session: AsyncSession, *, user_id: int, label: str,
    lo: Optional[date], hi: Optional[date],
) -> WindowStats:
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
    return WindowStats(
        label=label,
        spend=_gbp(int(cost or 0)),
        energy=_kwh(float(kwh or 0.0)),
        sessions=int(n or 0),
        avg_p_per_kwh=_pkwh(int(cost or 0), float(kwh_costed or 0.0)),
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

    # home = ac, public = dc
    type_stmt = _scoped(
        select(
            ChargingSession.charging_type,
            func.coalesce(func.sum(ChargingSession.cost_pence), 0),
            func.coalesce(func.sum(ChargingSession.kwh_added), 0.0),
        ).group_by(ChargingSession.charging_type)
    )
    home_p = home_k = pub_p = pub_k = 0
    for ctype, cost, kwh in (await session.execute(type_stmt)).all():
        if ctype == "ac":
            home_p, home_k = int(cost or 0), float(kwh or 0.0)
        elif ctype == "dc":
            pub_p, pub_k = int(cost or 0), float(kwh or 0.0)

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


async def build_usage_snapshot(
    session: AsyncSession, *, user_id: int, today: date, distance_unit: str
) -> UsageSnapshot:
    snap = UsageSnapshot(today=today.isoformat(), distance_unit=distance_unit)
    for label, lo, hi in _window_bounds(today):
        snap.windows.append(
            await _window_stats(session, user_id=user_id, label=label, lo=lo, hi=hi)
        )
    bounds = {label: (lo, hi) for label, lo, hi in _window_bounds(today)}
    for label in ("this month", "lifetime"):
        lo, hi = bounds[label]
        snap.splits.append(
            await _split_stats(session, user_id=user_id, label=label, lo=lo, hi=hi)
        )
    return snap
