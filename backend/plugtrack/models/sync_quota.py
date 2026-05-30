"""SyncQuotaDay — one row per calendar day, counting adapter requests.

Keyed by local date (not UTC) so the local-midnight reset aligns with the
user's day boundary. One row per day is upserted by the async helpers
below; the scheduler reads today's count to decide whether to stretch or
pause polling.

The counter is persisted (not in-memory) so a crash-loop or container
restart cannot reset the budget and allow the account quota to be blown.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as _text

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncQuotaDay(Base):
    """One row per local calendar day; request_count accumulates as getters fire."""

    __tablename__ = "sync_quota_day"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:
        return f"<SyncQuotaDay day={self.day} count={self.request_count}>"


# ---------------------------------------------------------------------------
# Async DB helpers — called from the worker (which owns a db_sessionmaker).
# ---------------------------------------------------------------------------

async def increment_request_count(session: AsyncSession, n: int = 1) -> int:
    """Add *n* to today's counter (local date). Returns the new total.

    Uses an upsert pattern:
    - If a row for today already exists, add *n* to request_count.
    - If no row exists yet, insert with request_count = n.

    Returns the updated count so callers can check against the budget
    without an extra read.
    """
    today = date.today()
    row = (
        await session.execute(
            select(SyncQuotaDay).where(SyncQuotaDay.day == today)
        )
    ).scalar_one_or_none()

    if row is None:
        row = SyncQuotaDay(day=today, request_count=n, updated_at=_utcnow())
        session.add(row)
    else:
        row.request_count += n
        row.updated_at = _utcnow()

    await session.flush()  # make the new value visible within the same session
    return row.request_count


async def read_today_count(session: AsyncSession) -> int:
    """Return today's request count, or 0 if no row exists yet."""
    today = date.today()
    row = (
        await session.execute(
            select(SyncQuotaDay).where(SyncQuotaDay.day == today)
        )
    ).scalar_one_or_none()
    return row.request_count if row is not None else 0


__all__ = [
    "SyncQuotaDay",
    "increment_request_count",
    "read_today_count",
]
