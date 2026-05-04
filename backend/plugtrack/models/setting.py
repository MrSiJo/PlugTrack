"""Setting model — DB-backed catalogue keyed on string `key`.

The catalogue (`plugtrack/settings/catalogue.py`) is the source of truth
for which keys exist; `seed_defaults` inserts any missing rows on every
startup, never overwriting user-provided values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        redacted = "***" if self.is_secret else self.value
        return f"<Setting key={self.key!r} value={redacted!r}>"
