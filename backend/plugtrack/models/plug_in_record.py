"""PlugInRecord model — full Phase 3 schema per spec §3.3.

A `plug_in_record` row represents a single physical plug-in event:
opened when telemetry shows the cable connected, closed when it shows
disconnected. ONE plug-in can produce MANY `charging_session` rows
(target raised mid-charge, pause-resume top-up, etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlugInRecord(Base):
    __tablename__ = "plug_in_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    car_id: Mapped[int] = mapped_column(ForeignKey("car.id"), nullable=False)

    plug_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plug_in_soc: Mapped[int] = mapped_column(Integer, nullable=False)
    plug_in_odometer_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    plug_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plug_out_soc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plug_out_odometer_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    location_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("location.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        state = "open" if self.plug_out_at is None else "closed"
        return f"<PlugInRecord id={self.id} car={self.car_id} {state}>"
