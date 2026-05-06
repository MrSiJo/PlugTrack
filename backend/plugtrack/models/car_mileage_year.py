"""CarMileageYear — annual mileage tracking periods.

One row per 12-month tracking period per car. The active period (the
one whose anniversary hasn't passed yet) has `closing_odometer_km`
NULL. When the anniversary rolls over, the active row is closed out
with the latest known odometer (from `ChargingSession`) and a new row
opens with that closing as its opening.

Distances are stored in km — UI converts on render via the user's
`distance_unit` setting. The user enters miles in the form; the API
layer converts to km before persisting.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CarMileageYear(Base):
    __tablename__ = "car_mileage_year"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    car_id: Mapped[int] = mapped_column(ForeignKey("car.id"), nullable=False)

    period_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    opening_odometer_km: Mapped[float] = mapped_column(Float, nullable=False)
    # NULL while the period is active. Set to the latest session odometer
    # at-or-before period_end_date when the anniversary rolls over.
    closing_odometer_km: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # Optional annual mileage cap (e.g. lease/insurance limit). Copied
    # forward to each new period on rollover; user can edit on the
    # active row at any time.
    annual_mileage_target_km: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_car_mileage_year_car", "car_id", "period_start_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<CarMileageYear id={self.id} car={self.car_id} "
            f"{self.period_start_date}..{self.period_end_date}>"
        )
