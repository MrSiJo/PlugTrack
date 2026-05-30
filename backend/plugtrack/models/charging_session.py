"""ChargingSession model — full Phase 3 schema per spec §3.3.

Distance fields use the `_km` suffix to enforce the storage convention
(everything stored in km; UI converts on render). The unique index on
`(car_id, telematics_session_id) WHERE telematics_session_id IS NOT
NULL` lets the synthesis layer (Phase 4) re-run idempotently without
inserting duplicates.

Cost columns:
- `cost_pence` is the computed cost (rounded to integer pence).
- `cost_basis` records WHICH branch of the precedence rule produced
  it (`override_total`, `override_per_kwh`, `location_free`,
  `location_rate`, `home_rate`, `unknown`).
- `tariff_p_per_kwh` is the per-kWh rate used (snapshot for forensic
  reconstruction; if the home rate later changes the historical
  session retains its original rate).
- `cost_per_kwh_override_p` and `total_cost_pence_override` are
  user-entered cost overlays. The cost service treats them as sacred —
  re-syncs never overwrite.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChargingSession(Base):
    __tablename__ = "charging_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    car_id: Mapped[int] = mapped_column(ForeignKey("car.id"), nullable=False)
    plug_in_record_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("plug_in_record.id"), nullable=True
    )

    # Denormalised so list queries are fast.
    date: Mapped[date] = mapped_column(Date, nullable=False)

    charge_start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    charge_end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    start_soc: Mapped[int] = mapped_column(Integer, nullable=False)
    end_soc: Mapped[int] = mapped_column(Integer, nullable=False)
    # `kwh_added` is the canonical figure used for cost computation. The
    # synthesis worker initialises it from the SoC delta × battery
    # capacity, but users typically overwrite it with the metered value
    # from their EVSE/wallbox via the edit form.
    kwh_added: Mapped[float] = mapped_column(Float, nullable=False)
    # `kwh_calculated` is the SoC-delta derivation, written by synthesis
    # alongside `kwh_added` and never updated by user edits. We surface
    # it next to the editable value so the user can compare metered vs
    # battery-implied energy and notice big losses.
    kwh_calculated: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Distance snapshot at charge_start_at — every distance column ends
    # in `_km` per the spec's distance-unit rule.
    odometer_at_session_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    charging_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )  # 'ac' | 'dc' | 'unknown'
    charging_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )  # 'timer' | 'manual' | 'profile' | 'unknown'
    battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    max_charge_current: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ---- Cost ----
    cost_pence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )  # 'override_total' | 'override_per_kwh' | 'location_free' |
       # 'location_rate' | 'home_rate' | 'unknown'
    tariff_p_per_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_per_kwh_override_p: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    total_cost_pence_override: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ---- Location overlay ----
    location_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("location.id"), nullable=True
    )
    user_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    charge_network: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    source: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # 'synthesis' | 'manual' | 'cariad'
    telematics_session_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    power_curve: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # ---- Reserved cariad columns — NULL on v1 synthesis. ----
    evse_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    station_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    energy_loss_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    authentication_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contract: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    voucher_amount_pence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    blocking_fees_pence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        # Partial unique: only enforced when telematics_session_id is set,
        # so manual sessions (NULL) don't collide.
        Index(
            "uq_session_car_telematics",
            "car_id",
            "telematics_session_id",
            unique=True,
            sqlite_where=text("telematics_session_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ChargingSession id={self.id} car={self.car_id} "
            f"date={self.date} {self.start_soc}->{self.end_soc}%>"
        )
