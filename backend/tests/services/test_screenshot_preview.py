import datetime as dt

import pytest
from sqlalchemy import select

from plugtrack.models import ChargingSession
from plugtrack.services.screenshot_commit import preview_merged_session
from plugtrack.services.screenshot_correlation import MergedSession


def _merged(**over):
    base = dict(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 16, 6, 59, tzinfo=dt.timezone.utc),
        energy_kwh=10.74, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name=None, location_address=None,
        network=None, peak_kw=2.0, confidence=0.91, source_kinds=["mycupra", "granny"],
    )
    base.update(over)
    return MergedSession(**base)


async def _home_rate(sm, p="19.26"):
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    async with sm() as s:
        await seed_defaults(s)
        row = (await s.execute(select(Setting).where(
            Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = p
        await s.commit()


@pytest.mark.asyncio
async def test_preview_projects_home_cost_without_persisting(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await preview_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        assert cs.kwh_added == 10.74            # delivered (granny)
        assert cs.charging_type == "ac"
        assert cs.cost_basis == "home_rate"
        assert cs.cost_pence == round(10.74 * 19.26)  # 207 -> £2.07
        rows = (await s.execute(select(ChargingSession))).scalars().all()
        assert rows == []                        # NOT persisted


@pytest.mark.asyncio
async def test_preview_mycupra_only_derives_kwh(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await preview_merged_session(
            s, user_id=user_id, car_id=car_id, merged=_merged(energy_kwh=None))
        assert cs.kwh_added > 0                  # promoted from SoC delta (battery)
        assert cs.cost_pence is not None and cs.cost_pence > 0
