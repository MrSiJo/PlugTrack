"""Dashboard spend trend — daily cost totals over a window.

Returns one entry per day in `[start, today]` (inclusive). Days with no
sessions return `cost_pence=0`. All filtering happens server-side and
respects multi-user isolation via `user_id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession


@dataclass(frozen=True)
class SpendDay:
    date: date_cls
    cost_pence: int


async def compute_spend_trend(
    session: AsyncSession,
    *,
    user_id: int,
    days: int = 30,
    today: date_cls | None = None,
) -> list[SpendDay]:
    """Return per-day spend totals for the trailing `days` days.

    `today` defaults to `date.today()` and is exposed as a param so tests
    can pin a date deterministically.
    """
    end = today if today is not None else date_cls.today()
    start = end - timedelta(days=days - 1)

    stmt = (
        select(
            ChargingSession.date,
            func.coalesce(func.sum(ChargingSession.cost_pence), 0),
        )
        .where(ChargingSession.user_id == user_id)
        .where(ChargingSession.date >= start)
        .where(ChargingSession.date <= end)
        .group_by(ChargingSession.date)
    )
    rows = (await session.execute(stmt)).all()
    by_date: dict[date_cls, int] = {row[0]: int(row[1] or 0) for row in rows}

    out: list[SpendDay] = []
    for i in range(days):
        d = start + timedelta(days=i)
        out.append(SpendDay(date=d, cost_pence=by_date.get(d, 0)))
    return out
