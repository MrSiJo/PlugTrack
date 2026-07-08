"""GPS-based location clustering.

Uses great-circle (haversine) distance between coordinate pairs to
cluster GPS observations. New observations within `radius_m` of an
existing user-owned location's centroid are matched to that location;
otherwise a new location is created with no name and no flags set
(unlabelled).

Reverse-geocoding lives in Phase 5. This module makes no third-party
calls.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.location import Location

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng pairs, in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


async def find_or_create_location(
    session: AsyncSession,
    user_id: int,
    lat: float,
    lng: float,
    radius_m: int = 100,
) -> tuple[Location, bool]:
    """Return the nearest existing location for this user within `radius_m`.

    If none, create a new location with `name=None`, `is_home=False`,
    `is_free=False`, `default_cost_per_kwh_p=None`. Returns
    `(location, was_created)`.
    """
    result = await session.execute(select(Location).where(Location.user_id == user_id))
    candidates = result.scalars().all()

    nearest: Location | None = None
    nearest_distance: float = float("inf")
    for candidate in candidates:
        distance = haversine_m(lat, lng, candidate.centroid_lat, candidate.centroid_lng)
        if distance <= radius_m and distance < nearest_distance:
            nearest = candidate
            nearest_distance = distance

    if nearest is not None:
        return nearest, False

    new_location = Location(
        user_id=user_id,
        name=None,
        centroid_lat=lat,
        centroid_lng=lng,
        radius_m=radius_m,
        is_home=False,
        is_free=False,
        default_cost_per_kwh_p=None,
    )
    session.add(new_location)
    await session.flush()  # populate id without forcing a commit on the caller
    return new_location, True
