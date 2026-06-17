# backend/tests/services/test_screenshot_commit_home.py
import datetime as dt
import pytest

from plugtrack.services.screenshot_correlation import MergedSession
from plugtrack.services.screenshot_commit import commit_merged_session


def _merged(**over):
    base = dict(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 16, 6, 59, tzinfo=dt.timezone.utc),
        energy_kwh=None, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name=None, location_address=None,
        network=None, peak_kw=2.0, confidence=0.95, source_kinds=["mycupra"],
    )
    base.update(over)
    return MergedSession(**base)


async def _set_home_rate(test_sessionmaker, pence="19.26"):
    from sqlalchemy import select
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        row = (await s.execute(select(Setting).where(
            Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = pence
        await s.commit()


@pytest.mark.asyncio
async def test_home_mycupra_only_derives_kwh_and_costs_home_rate(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car  # car battery_kwh from the fixture
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit(); await s.refresh(cs)
    assert cs.charging_type == "ac"
    assert cs.kwh_added > 0          # promoted from SoC delta
    assert cs.kwh_calculated > 0
    assert cs.cost_basis == "home_rate"
    assert cs.cost_pence is not None and cs.cost_pence > 0


@pytest.mark.asyncio
async def test_home_with_granny_uses_delivered_and_matches_location(test_sessionmaker, seeded_user_car):
    from plugtrack.models import Location
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="Home", is_free=False,
                       default_cost_per_kwh_p=19.26, centroid_lat=0.0, centroid_lng=0.0,
                       radius_m=50))
        await s.commit()
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", source_kinds=["mycupra", "granny"]))
        await s.commit(); await s.refresh(cs)
    assert cs.kwh_added == 9.3                 # delivered wins
    assert cs.kwh_calculated > 0               # SoC banked
    assert cs.location_id is not None          # matched "home"
    assert cs.cost_basis == "location_rate"
    assert cs.charging_type == "ac"


@pytest.mark.asyncio
async def test_network_charge_is_dc(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=37.9, cost_total_pence=1706, network="Tesla",
                           soc_start=None, soc_end=None, source_kinds=["tesla"]))
        await s.commit(); await s.refresh(cs)
    assert cs.charging_type == "dc"
    assert cs.cost_basis == "override_total" and cs.cost_pence == 1706
