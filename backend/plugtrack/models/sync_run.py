"""SyncRun model — full Phase 4 schema.

One row per sync attempt per car. Used both for forensic debugging (what
happened during a poll?) and for resuming the state machine across
process restarts (`state_observed` is the persisted state).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("car.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'periodic' | 'force' | 'transition_followup'
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="periodic")

    # Latest state observed by the synthesiser. Persisted so process
    # restarts resume the state machine without re-deriving from scratch.
    state_observed: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # JSON list of transition payloads emitted during this run.
    transitions_emitted: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    sessions_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    def __repr__(self) -> str:
        return f"<SyncRun id={self.id} car={self.car_id} status={self.status}>"
