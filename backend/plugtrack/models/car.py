"""Car model — full Phase 3 schema.

Per spec §3.3:

    car
        id, user_id, make, model, vin (nullable, encrypted), battery_kwh,
        nominal_efficiency_mi_per_kwh,
        provider ('cupra_connect' | 'manual'),
        provider_vehicle_id (nullable),
        active, created_at, updated_at

VIN is stored encrypted at rest. The `vin` Python attribute is a
property that round-trips Fernet encryption transparently — call sites
read/write plaintext, the DB stores ciphertext in the `vin_encrypted`
column.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..bootstrap import get_settings
from ..security.crypto import decrypt_secret, encrypt_secret
from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Car(Base):
    __tablename__ = "car"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    make: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # VIN ciphertext; never queried by value. The `vin` property below
    # is the only public access path.
    vin_encrypted: Mapped[Optional[str]] = mapped_column(
        "vin_encrypted", String(512), nullable=True
    )

    battery_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    nominal_efficiency_mi_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)

    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="cupra_connect"
    )
    provider_vehicle_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    # ---------------------------------------------------------------
    # VIN encryption — `vin` is plaintext on the Python side; the
    # column on disk is `vin_encrypted` (Fernet ciphertext).
    # ---------------------------------------------------------------

    @property
    def vin(self) -> Optional[str]:
        if not self.vin_encrypted:
            return None
        return decrypt_secret(self.vin_encrypted, get_settings().app_secret_key)

    @vin.setter
    def vin(self, value: Optional[str]) -> None:
        if value is None or value == "":
            self.vin_encrypted = None
        else:
            self.vin_encrypted = encrypt_secret(value, get_settings().app_secret_key)

    @property
    def display_name(self) -> str:
        return self.name or f"{self.make} {self.model}"

    def __repr__(self) -> str:
        return f"<Car id={self.id} {self.make} {self.model}>"
