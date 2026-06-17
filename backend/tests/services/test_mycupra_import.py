"""MyCupra CSV backfill importer.

Matching policy: idempotent by Session ID; else heuristic match on SoC + local
start time. Matched rows get ONLY actual_charge_seconds + telematics_session_id
(kWh/SoC/cost/source stay untouched). Unmatched rows are inserted as
source='import'. CSV times are UTC; the DB stores Europe/London local naive.
"""
import datetime as dt

import pytest
from sqlalchemy import func, select

from plugtrack.models import ChargingSession, Location, Setting
from plugtrack.settings.seeds import seed_defaults
from plugtrack.services.mycupra_import import (
    format_report, parse_csv_rows, parse_location_map, run_import,
)


def _csv_dict(*, sid="s1", started="2026-06-15T18:27:30Z", ended="2026-06-16T05:59:21Z",
              charging_s=41511, actual_s=13783, energy=6.0, isoc=67, fsoc=80):
    return {
        "Session ID": sid, "Session started": started, "Session ended": ended,
        "Charging time (s)": str(charging_s), "Actual charging time (s)": str(actual_s),
        "Total energy (kWh)": f"{energy:.2f}", "Battery energy (kWh)": "",
        "Comfort energy (kWh)": "", "Initial state of charge (%)": f"{isoc:.2f}",
        "Final state of charge (%)": f"{fsoc:.2f}", "Total price": "", "Energy price": "",
        "Blocking fees": "", "Voucher amount used": "", "Location name": "", "Profile": "",
    }


async def _seed_home_rate(sm, pence="19.26"):
    async with sm() as s:
        await seed_defaults(s)
        row = (await s.execute(
            select(Setting).where(Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = pence
        await s.commit()


async def _add_session(sm, *, user_id, car_id, start_local, isoc, fsoc, kwh,
                       charging_type="ac", **kw):
    async with sm() as s:
        cs = ChargingSession(
            user_id=user_id, car_id=car_id, date=start_local.date(),
            charge_start_at=start_local,
            charge_end_at=start_local + dt.timedelta(hours=1),
            start_soc=isoc, end_soc=fsoc, kwh_added=kwh, charging_type=charging_type,
            charging_mode="manual", source="manual", **kw)
        s.add(cs)
        await s.commit()
        await s.refresh(cs)
        return cs.id


def test_parse_converts_utc_to_london_local():
    rows = parse_csv_rows([_csv_dict(started="2026-06-15T18:27:30Z")])
    assert len(rows) == 1
    r = rows[0]
    assert r.start_local == dt.datetime(2026, 6, 15, 19, 27, 30)  # BST = +1h
    assert r.actual_s == 13783
    assert r.soc_start == 67 and r.soc_end == 80
    assert r.energy_kwh == 6.0
    assert r.session_id == "s1"


@pytest.mark.asyncio
async def test_update_existing_match_sets_actual_and_id_only(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    sid = await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 6, 15, 19, 27), isoc=67, fsoc=80, kwh=10.74)
    rows = parse_csv_rows([_csv_dict(sid="cupra-1", energy=6.0, isoc=67, fsoc=80)])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert len(report.updated) == 1 and not report.inserted and not report.skipped
    async with test_sessionmaker() as s:
        cs = await s.get(ChargingSession, sid)
        assert cs.actual_charge_seconds == 13783
        assert cs.telematics_session_id == "cupra-1"
        assert cs.kwh_added == 10.74         # sacred — unchanged
        assert cs.source == "manual"         # unchanged
        assert cs.start_soc == 67 and cs.end_soc == 80


@pytest.mark.asyncio
async def test_insert_missing_creates_import_source(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    rows = parse_csv_rows([_csv_dict(
        sid="cupra-x", started="2026-06-14T15:30:05Z", ended="2026-06-15T05:39:07Z",
        actual_s=17536, energy=11.0, isoc=47, fsoc=63)])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert len(report.inserted) == 1 and not report.updated
    async with test_sessionmaker() as s:
        cs = (await s.execute(select(ChargingSession).where(
            ChargingSession.telematics_session_id == "cupra-x"))).scalar_one()
        assert cs.source == "import"
        assert cs.actual_charge_seconds == 17536
        assert cs.start_soc == 47 and cs.end_soc == 63
        assert cs.kwh_added == 11.0
        assert cs.charging_type == "ac"
        assert cs.cost_basis == "home_rate"
        assert cs.charge_start_at.replace(tzinfo=None) == dt.datetime(2026, 6, 14, 16, 30, 5)


@pytest.mark.asyncio
async def test_idempotent_rerun_no_duplicates(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    rows = parse_csv_rows([_csv_dict(
        sid="cupra-x", started="2026-06-14T15:30:05Z", actual_s=17536, energy=11.0, isoc=47, fsoc=63)])
    async with test_sessionmaker() as s:
        await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    async with test_sessionmaker() as s:
        report2 = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert report2.skipped and not report2.inserted and not report2.updated
    async with test_sessionmaker() as s:
        n = (await s.execute(select(func.count()).select_from(ChargingSession).where(
            ChargingSession.telematics_session_id == "cupra-x"))).scalar_one()
        assert n == 1


@pytest.mark.asyncio
async def test_same_day_multiples_match_distinctly(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    a = await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 5, 27, 18, 56), isoc=60, fsoc=67, kwh=4.0)
    b = await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 5, 27, 19, 24), isoc=67, fsoc=90, kwh=15.39)
    rows = parse_csv_rows([
        _csv_dict(sid="m1", started="2026-05-27T17:56:25Z", actual_s=653, energy=4.0, isoc=60, fsoc=67),
        _csv_dict(sid="m2", started="2026-05-27T18:24:45Z", actual_s=863, energy=13.0, isoc=67, fsoc=90),
    ])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert len(report.updated) == 2 and not report.inserted
    async with test_sessionmaker() as s:
        ca = await s.get(ChargingSession, a)
        cb = await s.get(ChargingSession, b)
        assert ca.telematics_session_id == "m1" and ca.actual_charge_seconds == 653
        assert cb.telematics_session_id == "m2" and cb.actual_charge_seconds == 863


@pytest.mark.asyncio
async def test_energy_endsoc_fallback_matches_divergent_start(test_sessionmaker, seeded_user_car):
    """A DC row whose start SoC was mis-entered (78 in DB vs 64 in CSV) and whose
    start time is minutes off should still match on same-day + end-SoC + energy,
    so it updates rather than inserting a duplicate. Start SoC stays sacred."""
    user_id, car_id = seeded_user_car
    sid = await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 6, 8, 13, 35), isoc=78, fsoc=90, kwh=15.9,
        charging_type="dc")
    rows = parse_csv_rows([_csv_dict(
        sid="d1", started="2026-06-08T12:49:00Z", ended="2026-06-08T13:08:00Z",
        actual_s=1059, energy=16.0, isoc=64, fsoc=90)])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert len(report.updated) == 1 and not report.inserted
    async with test_sessionmaker() as s:
        cs = await s.get(ChargingSession, sid)
        assert cs.telematics_session_id == "d1"
        assert cs.actual_charge_seconds == 1059
        assert cs.start_soc == 78          # sacred — NOT overwritten with 64


@pytest.mark.asyncio
async def test_fallback_respects_distinct_end_soc_same_day(test_sessionmaker, seeded_user_car):
    """Two charges on one day with different end-SoC: a CSV row matching neither
    on the tight rule must NOT fall back onto the wrong one — it inserts."""
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    # DB has a morning charge ending at 70%.
    await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 6, 12, 15, 25), isoc=56, fsoc=70, kwh=10.0)
    # CSV row is a different afternoon charge ending at 80% — must insert.
    rows = parse_csv_rows([_csv_dict(
        sid="x1", started="2026-06-12T14:03:00Z", actual_s=16074, energy=9.0,
        isoc=66, fsoc=80)])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=True)
        await s.commit()
    assert len(report.inserted) == 1 and not report.updated


@pytest.mark.asyncio
async def test_format_report_summarises_actions(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    sid = await _add_session(
        test_sessionmaker, user_id=user_id, car_id=car_id,
        start_local=dt.datetime(2026, 6, 15, 19, 27), isoc=67, fsoc=80, kwh=10.74)
    rows = parse_csv_rows([
        _csv_dict(sid="cupra-1", started="2026-06-15T18:27:30Z", isoc=67, fsoc=80),
        _csv_dict(sid="cupra-x", started="2026-06-14T15:30:05Z", actual_s=17536,
                  energy=11.0, isoc=47, fsoc=63),
    ])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=False)
    text = format_report(report)
    assert "1 insert" in text and "1 update" in text
    assert "UPDATE" in text and "INSERT" in text
    assert str(sid) in text  # references the matched DB session


def test_parse_location_map():
    assert parse_location_map("2026-06-10=8,2026-06-14=1") == {
        dt.date(2026, 6, 10): 8, dt.date(2026, 6, 14): 1}
    assert parse_location_map("") == {}
    assert parse_location_map(None) == {}


@pytest.mark.asyncio
async def test_insert_assigns_free_location_by_date(test_sessionmaker, seeded_user_car):
    """Inserted rows get a location by date; a free location yields £0 cost."""
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        loc = Location(user_id=user_id, name="Cottage", is_free=True,
                       centroid_lat=0.0, centroid_lng=0.0, radius_m=100)
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
        loc_id = loc.id
    rows = parse_csv_rows([_csv_dict(
        sid="c1", started="2026-06-10T10:30:00Z", actual_s=14467, energy=8.0,
        isoc=67, fsoc=80)])
    async with test_sessionmaker() as s:
        report = await run_import(
            s, user_id=user_id, car_id=car_id, rows=rows, apply=True,
            location_by_date={dt.date(2026, 6, 10): loc_id})
        await s.commit()
    assert len(report.inserted) == 1
    async with test_sessionmaker() as s:
        cs = (await s.execute(select(ChargingSession).where(
            ChargingSession.telematics_session_id == "c1"))).scalar_one()
        assert cs.location_id == loc_id
        assert cs.cost_basis == "location_free"
        assert cs.cost_pence == 0


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    rows = parse_csv_rows([_csv_dict(
        sid="cupra-x", started="2026-06-14T15:30:05Z", actual_s=17536, energy=11.0, isoc=47, fsoc=63)])
    async with test_sessionmaker() as s:
        report = await run_import(s, user_id=user_id, car_id=car_id, rows=rows, apply=False)
        await s.commit()
    assert len(report.inserted) == 1   # the plan
    async with test_sessionmaker() as s:
        n = (await s.execute(select(func.count()).select_from(ChargingSession))).scalar_one()
        assert n == 0                  # but nothing was written
