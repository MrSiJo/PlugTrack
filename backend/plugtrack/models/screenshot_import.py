"""Staging row for a single ingested charge screenshot.

Each Telegram photo is extracted to `extracted` (the OpenAI JSON), then
correlated with sibling rows into merged charging sessions. `image_sha256`
dedupes re-sent screenshots per user. `status` walks staged -> committed
(links `created_session_id`) or staged -> discarded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScreenshotImport(Base):
    __tablename__ = "screenshot_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    extracted: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="staged")
    group_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_session_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("charging_session.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("uq_screenshot_user_sha", "user_id", "image_sha256", unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScreenshotImport id={self.id} status={self.status} source={self.source}>"
