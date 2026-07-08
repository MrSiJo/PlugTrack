# backend/tests/services/test_location_match.py
import pytest
from plugtrack.services.screenshot_commit import match_location_by_name


@pytest.mark.asyncio
async def test_match_is_case_insensitive(test_sessionmaker, seeded_user_car):
    from plugtrack.models import Location

    user_id, _car_id = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(
            Location(
                user_id=user_id,
                name="Home",
                is_free=False,
                default_cost_per_kwh_p=19.26,
                centroid_lat=0.0,
                centroid_lng=0.0,
                radius_m=50,
            )
        )
        await s.commit()
    async with test_sessionmaker() as s:
        assert await match_location_by_name(s, user_id=user_id, name="home") is not None
        assert await match_location_by_name(s, user_id=user_id, name="HOME") is not None
        assert await match_location_by_name(s, user_id=user_id, name="garage") is None
        assert await match_location_by_name(s, user_id=user_id, name=None) is None
