"""Persisted snapshot of the in-memory `CarSyncState`.

The orchestrator keeps state in RAM for the request hot-path, but a
container restart would otherwise lose every car's last-known
battery/range/state until the next sync fires. We upsert a row per car
on each successful sync and rehydrate the orchestrator's `_state` dict
during lifespan startup.

One row per car (PK on `car_id`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CarStateSnapshot(Base):
    __tablename__ = "car_state"

    car_id: Mapped[int] = mapped_column(
        ForeignKey("car.id", ondelete="CASCADE"), primary_key=True
    )
    last_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_soc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_target_soc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_electric_range_km: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    last_charging_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    last_battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_max_charge_current: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    last_charging_estimated_end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_position_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_position_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_location_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL"), nullable=True
    )
    last_car_captured_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<CarStateSnapshot car={self.car_id} state={self.last_state} "
            f"soc={self.last_soc}>"
        )
