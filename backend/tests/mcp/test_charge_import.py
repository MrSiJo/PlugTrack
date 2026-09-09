"""Aster import boundary: synthetic records only, no extraction/API calls."""

import asyncio
import datetime as dt

import pytest
from plugtrack.mcp import tools
from plugtrack.models import Car, ChargingSession
from sqlalchemy import select


def extraction(**changes):
    data = dict(
        start_at="2026-09-09T10:00:00+01:00",
        end_at="2026-09-09T11:00:00+01:00",
        energy_kwh=20.0,
        cost_total_pence=700,
        soc_start=20,
        soc_end=60,
    )
    data.update(changes)
    return data


@pytest.mark.asyncio
async def test_list_cars_is_scoped(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        rows = await tools.list_cars(s, user)
        assert [r["id"] for r in rows] == [car]
        assert rows[0]["name"]
        assert "vin" not in rows[0]
        assert await tools.list_cars(s, user + 100) == []


@pytest.mark.asyncio
async def test_propose_preview_then_commit_replay_and_duplicate(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        proposal = await tools.propose_import_charge(
            s, user, car_id=car, extractions=[extraction()]
        )
        assert proposal["preview"][0]["cost_pence"] == 700
        assert proposal["preview"][0]["source"] == "aster"
        assert proposal["preview"][0]["car_id"] == car
        assert (await s.execute(select(ChargingSession))).scalars().all() == []
        token = proposal["change_token"]
        assert "error" in await tools.commit_change(s, user + 100, token)
        result = await tools.commit_change(s, user, token)
        assert result["ok"] and len(result["charge_ids"]) == 1
        # A different proposal must not evict the replay receipt.
        duplicate = await tools.propose_import_charge(
            s, user, car_id=car, extractions=[extraction()]
        )
        assert await tools.commit_change(s, user, token) == result
        second = await tools.commit_change(s, user, duplicate["change_token"])
        assert second == {"ok": True, "charge_ids": [], "duplicates_skipped": 1}
        rows = (await s.execute(select(ChargingSession))).scalars().all()
        assert len(rows) == 1
        assert rows[0].source == "aster" and rows[0].total_cost_pence_override == 700


@pytest.mark.asyncio
async def test_commit_import_serializes_concurrent_proposals(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        a = await tools.propose_import_charge(s, user, car_id=car, extractions=[extraction()])
        b = await tools.propose_import_charge(s, user, car_id=car, extractions=[extraction()])

    async def commit(token):
        async with test_sessionmaker() as s:
            return await tools.commit_change(s, user, token)

    results = await asyncio.gather(commit(a["change_token"]), commit(b["change_token"]))
    assert sum(len(r["charge_ids"]) for r in results) == 1
    async with test_sessionmaker() as s:
        assert len((await s.execute(select(ChargingSession))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_import_rechecks_car_and_expiry(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        assert "error" in await tools.propose_import_charge(
            s, user + 100, car_id=car, extractions=[extraction()]
        )
        p = await tools.propose_import_charge(s, user, car_id=car, extractions=[extraction()])
        row = await s.get(Car, car)
        row.active = False
        await s.commit()
        assert "error" in await tools.commit_change(s, user, p["change_token"])
        row.active = True
        await s.commit()
        tools._CHANGE_STORE[p["change_token"]]["created_at"] -= dt.timedelta(minutes=11)
        assert "expired" in (await tools.commit_change(s, user, p["change_token"]))["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "records",
    [
        [],
        [extraction(energy_kwh=-1)],
        [extraction(soc_start=101)],
        [extraction(start_at="bad")],
        [extraction(start_at="2026-09-09T10:00:00")],
        [extraction(end_at="2026-09-08T10:00:00Z")],
        [extraction(energy_kwh=float("inf"))],
        [extraction(odometer=10)],
        [extraction(power_curve=[[2, 1]])],
        [extraction(surprise="discarded?")],
        [extraction(start_at=None, end_at=None)],
        [extraction()] * 11,
    ],
)
async def test_import_rejects_invalid_input(test_sessionmaker, seeded_user_car, records):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        assert "error" in await tools.propose_import_charge(
            s, user, car_id=car, extractions=records
        )
        assert (await s.execute(select(ChargingSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_import_correlates_timed_and_meter_without_network(
    test_sessionmaker, seeded_user_car, monkeypatch
):
    from plugtrack.services import ingest_location

    async def forbidden(*args, **kwargs):
        raise AssertionError("external geocoding must not run")

    monkeypatch.setattr(ingest_location, "resolve_ingested_location", forbidden)
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(
                    energy_kwh=None, cost_total_pence=None, location_name="Synthetic station"
                ),
                dict(energy_kwh=20, actual_charge_seconds=3600),
            ],
        )
        assert len(p["preview"]) == 1 and p["preview"][0]["kwh"] == 20
        assert p["warnings"]
        result = await tools.commit_change(s, user, p["change_token"])
        assert result["ok"]
        cs = (await s.execute(select(ChargingSession))).scalar_one()
        assert cs.user_label == "Synthetic station" and cs.location_id is None


@pytest.mark.asyncio
async def test_import_rejects_changed_reviewed_energy(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(energy_kwh=None, cost_total_pence=None),
            ],
        )
        row = await s.get(Car, car)
        row.battery_kwh += 10
        await s.commit()
        result = await tools.commit_change(s, user, p["change_token"])
        assert "changed since preview" in result["error"]
        assert (await s.execute(select(ChargingSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_import_dedupes_soc_energy_promoted_from_zero(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        for expected_skips in (0, 1):
            p = await tools.propose_import_charge(
                s,
                user,
                car_id=car,
                extractions=[
                    extraction(energy_kwh=0, cost_total_pence=None),
                ],
            )
            assert p["preview"][0]["kwh"] > 0
            result = await tools.commit_change(s, user, p["change_token"])
            assert result["duplicates_skipped"] == expected_skips
        assert len((await s.execute(select(ChargingSession))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_import_validates_merged_time_window(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(end_at=None),
                {"end_at": "2026-09-09T09:00:00+01:00"},
            ],
        )
        assert "error" in p


@pytest.mark.asyncio
async def test_import_preview_includes_reviewable_curve(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(actual_charge_seconds=3600, power_curve=[[0, 0], [0.5, 20], [1, 0]]),
            ],
        )
        assert p["preview"][0]["actual_charge_seconds"] == 3600
        assert p["preview"][0]["power_curve"] == [[0, 20, 0.0], [1800, 40, 20.0], [3600, 60, 0.0]]


@pytest.mark.asyncio
async def test_import_and_telegram_share_atomic_duplicate_guard(
    test_sessionmaker, seeded_user_car, monkeypatch
):
    from plugtrack.mcp.charge_import import ChargeExtraction
    from plugtrack.services import screenshot_commit
    from plugtrack.services.screenshot_correlation import correlate
    from plugtrack.services.screenshot_extraction import Extraction

    original_check = screenshot_commit._is_duplicate

    async def yielding_check(*args, **kwargs):
        found = await original_check(*args, **kwargs)
        # Force both callers past an unprotected read before either can insert.
        await asyncio.sleep(0.05)
        return found

    monkeypatch.setattr(screenshot_commit, "_is_duplicate", yielding_check)
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(s, user, car_id=car, extractions=[extraction()])

    async def aster():
        async with test_sessionmaker() as s:
            return await tools.commit_change(s, user, p["change_token"])

    async def telegram():
        merged = correlate(
            [Extraction(**ChargeExtraction.model_validate(extraction()).model_dump(mode="json"))]
        )[0]
        async with test_sessionmaker() as s:
            result = await screenshot_commit.commit_merged_session(
                s, user_id=user, car_id=car, merged=merged
            )
            await s.commit()
            return result

    await asyncio.gather(aster(), telegram())
    async with test_sessionmaker() as s:
        assert len((await s.execute(select(ChargingSession))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_import_normalizes_equivalent_instants_to_london(test_sessionmaker, seeded_user_car):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        p = await tools.propose_import_charge(s, user, car_id=car, extractions=[extraction()])
        assert (await tools.commit_change(s, user, p["change_token"]))["charge_ids"]
        q = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(start_at="2026-09-09T09:00:00Z", end_at="2026-09-09T10:00:00Z"),
            ],
        )
        assert q["preview"][0]["charge_start_at"] == "2026-09-09T10:00:00+01:00"
        assert (await tools.commit_change(s, user, q["change_token"]))["duplicates_skipped"] == 1


@pytest.mark.asyncio
async def test_import_keeps_missing_meter_energy_duplicate_safeguard(
    test_sessionmaker, seeded_user_car
):
    user, car = seeded_user_car
    async with test_sessionmaker() as s:
        first = await tools.propose_import_charge(
            s, user, car_id=car, extractions=[extraction(energy_kwh=50)]
        )
        assert (await tools.commit_change(s, user, first["change_token"]))["charge_ids"]
        inferred = await tools.propose_import_charge(
            s,
            user,
            car_id=car,
            extractions=[
                extraction(energy_kwh=None, cost_total_pence=None),
            ],
        )
        result = await tools.commit_change(s, user, inferred["change_token"])
        assert result["duplicates_skipped"] == 1
        row = (await s.execute(select(ChargingSession))).scalar_one()
        assert row.kwh_added == 50 and row.total_cost_pence_override == 700
