"""Location model — full Phase 3 schema per spec §3.3.

NO `category` enum: labelling is fully user-driven (free-text `name`,
plus `is_home` / `is_free` boolean flags). The cost-precedence rule
hinges on `is_free` and `default_cost_per_kwh_p` only — `is_home` is a
pure analytics tag.

Locations are clustered by `find_or_create_location` (see
`services/location_clustering.py`). Reverse-geocoding to populate
`address` is deferred to Phase 5; new locations are created with
`address=None`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Location(Base):
    __tablename__ = "location"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)

    # Free-text user label. NULL until the user labels the location for
    # the first time (post-session-labelling flow).
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Reverse-geocode metadata — populated in Phase 5.
    address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    address_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # User-driven flags. is_home is purely an analytics tag; is_free
    # zeroes out cost in the cost-precedence rule (spec §3.3 lines
    # 143–162).
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_cost_per_kwh_p: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    # Default charge network for sessions at this location. When a sync
    # closes a session here and the session has no charge_network set,
    # this value is copied across. User edits to a session's network are
    # sacred — never overwritten on re-sync. Useful for tagging the home
    # location with the energy supplier (e.g. "Outfox Energy") and
    # commercial sites with the network operator (e.g. "MFG", "Tesla").
    default_charge_network: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_visited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        label = self.name or f"unlabelled@{self.centroid_lat:.4f},{self.centroid_lng:.4f}"
        return f"<Location id={self.id} {label}>"
