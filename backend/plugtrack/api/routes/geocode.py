"""Forward-geocoding route — resolve an address / place query to coordinates.

GET /api/geocode?q=...
    auth required. Uses the configured geocoding provider's `forward()`
    (Nominatim by default — free, keyless). Returns
    `{address, lat, lng, provider}` on a hit, 404 when there is no match or
    geocoding is disabled.

This is the forward complement to the reverse-geocode background task that
populates `Location.address` on creation. It lets the UI turn a typed
address ("Instavolt McDonalds, Lysander Road, Yeovil") into a centroid for
a new location instead of requiring a map-pick.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Setting
from ...services.geocoding import get_provider

router = APIRouter(prefix="/api/geocode", tags=["geocode"])


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def _geocoding_settings(session: AsyncSession) -> dict:
    keys = ["geocoding_enabled", "geocoding_provider", "geocoding_api_key"]
    rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    return {r.key: r.value for r in rows}


@router.get("")
async def geocode(
    request: Request,
    q: str = Query(min_length=1, max_length=256),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _user_id(request)
    provider = get_provider(await _geocoding_settings(session))
    result = await provider.forward(q)
    if result is None:
        raise HTTPException(status_code=404, detail="No match for that address")
    return {
        "address": result.address,
        "lat": result.lat,
        "lng": result.lng,
        "provider": result.provider,
    }
