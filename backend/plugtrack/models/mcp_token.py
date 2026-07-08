"""MCPToken model — per-user bearer tokens for the MCP HTTP server.

Tokens are hashed at rest (sha256 with app_secret pepper). The plaintext
is shown once at mint time and never stored. Tokens are scoped
("read" | "readwrite") and revocable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MCPToken(Base):
    __tablename__ = "mcp_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # sha256(app_secret + plaintext_token); never the plaintext
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "read" or "readwrite"
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MCPToken id={self.id} user_id={self.user_id} "
            f"name={self.name!r} scope={self.scope!r}>"
        )
