from __future__ import annotations

import datetime as dt

import pytest

from plugtrack.models import ChargingSession
from plugtrack.services.usage_stats import build_usage_snapshot


async def _mk(sm, *, user_id, car_id, when, kwh, cost_pence, ctype="ac", network=None, source="manual"):
    async with sm() as s:
        s.add(ChargingSession(
            user_id=user_id, car_id=car_id, date=when, start_soc=20, end_soc=80,
            kwh_added=kwh, charging_type=ctype, charging_mode="manual",
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence is not None else "unknown",
            charge_network=network, source=source,
            charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.timezone.utc),
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_usage_snapshot_window_and_split_strings(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    today = dt.date(2026, 6, 17)
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 2), kwh=10.0, cost_pence=200, ctype="ac")
    await _mk(test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 4), kwh=30.0, cost_pence=1500, ctype="dc", network="Tesla")

    async with test_sessionmaker() as s:
        snap = await build_usage_snapshot(s, user_id=uid, today=today, distance_unit="mi")

    tm = next(w for w in snap.windows if w.label == "this month")
    assert tm.sessions == 2
    assert tm.spend == "£17.00"
    assert tm.energy == "40.0 kWh"
    assert tm.avg_p_per_kwh == "42.5 p/kWh"

    split = next(sp for sp in snap.splits if sp.label == "this month")
    assert split.home == "£2.00 over 10.0 kWh"
    assert split.public == "£15.00 over 30.0 kWh"
    assert split.by_network == {"Tesla": "£15.00 over 30.0 kWh"}
