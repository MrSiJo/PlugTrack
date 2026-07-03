# backend/tests/services/test_screenshot_commit.py
import datetime as dt
import pytest

from plugtrack.models import Location
from plugtrack.services.screenshot_correlation import MergedSession
from plugtrack.services.screenshot_commit import commit_merged_session


def _merged(**over):
    base = dict(
        start_at=dt.datetime(2026, 6, 12, 14, 25, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 12, 14, 40, tzinfo=dt.timezone.utc),
        energy_kwh=9.78, cost_total_pence=851, cost_per_kwh_pence=87.0,
        soc_start=56, soc_end=70, location_name="Land's End Car Park",
        location_address="TR19 7AA", network="Osprey", peak_kw=40.0,
        confidence=0.95, source_kinds=["mycupra", "osprey"],
    )
    base.update(over)
    return MergedSession(**base)


@pytest.mark.asyncio
async def test_commit_creates_session_with_override_total(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit()
        await s.refresh(cs)
    assert cs.kwh_added == 9.78
    assert cs.total_cost_pence_override == 851
    assert cs.cost_basis == "override_total"
    assert cs.cost_pence == 851
    assert cs.start_soc == 56 and cs.end_soc == 70
    assert cs.charge_network == "Osprey"
    assert cs.source == "telegram"


@pytest.mark.asyncio
async def test_commit_snapshots_location_network_when_session_blank(test_sessionmaker, seeded_user_car):
    # A home AC charge carries no network in the screenshot. If it links to a
    # location whose default_charge_network is set (e.g. the user's energy
    # supplier), that network is snapshotted onto the session at commit time.
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="Home", is_home=True,
                       centroid_lat=51.0, centroid_lng=-2.6, radius_m=100,
                       default_charge_network="Outfox Energy"))
        await s.commit()
    merged = _merged(network=None, cost_total_pence=None, cost_per_kwh_pence=None,
                     location_name="home", location_address=None)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=merged)
        await s.commit()
        await s.refresh(cs)
    assert cs.charge_network == "Outfox Energy"


@pytest.mark.asyncio
async def test_commit_leaves_network_blank_for_placeholder_location(test_sessionmaker, seeded_user_car):
    # A location whose default is a placeholder ("Unknown Network") must NOT be
    # snapshotted — the session stays blank so it aggregates under "Unknown".
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="Cottage", centroid_lat=50.1, centroid_lng=-5.6,
                       radius_m=100, default_charge_network="Unknown Network"))
        await s.commit()
    merged = _merged(network=None, cost_total_pence=None, cost_per_kwh_pence=None,
                     location_name="Cottage", location_address=None)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=merged)
        await s.commit()
        await s.refresh(cs)
    assert not cs.charge_network


@pytest.mark.asyncio
async def test_commit_dedupes_overlapping_same_energy(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit()
        dup = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
    assert dup is None  # deduped
