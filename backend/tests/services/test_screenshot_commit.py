# backend/tests/services/test_screenshot_commit.py
import datetime as dt
import pytest

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
    assert cs.source == "import"


@pytest.mark.asyncio
async def test_commit_dedupes_overlapping_same_energy(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit()
        dup = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
    assert dup is None  # deduped
