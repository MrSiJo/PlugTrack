"""Tests for plugtrack.services.digest — weekly and monthly digest builders.

Fixed ``now``: 2026-06-24 09:00 UTC (a Wednesday in week 3 of June 2026).

Week/month boundary math:
- Reported week  = Mon 2026-06-15 → Sun 2026-06-21  (the full Mon-Sun BEFORE this week)
- Previous week  = Mon 2026-06-08 → Sun 2026-06-14
- Reported month = May 2026  (previous calendar month)
- Previous month = April 2026
"""

from __future__ import annotations

import datetime as dt

import pytest
from plugtrack.models import Car, CarMileageYear, ChargingSession, Setting
from plugtrack.services.digest import _delta_phrase, build_monthly_digest, build_weekly_digest
from plugtrack.services.mileage_tracking import KM_PER_MILE
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Fixed "now" for all tests
# ---------------------------------------------------------------------------
NOW = dt.datetime(2026, 6, 24, 9, 0, 0, tzinfo=dt.UTC)

# Reported/previous windows
REP_WEEK_LO = dt.date(2026, 6, 15)  # Monday
REP_WEEK_HI = dt.date(2026, 6, 21)  # Sunday
PRV_WEEK_LO = dt.date(2026, 6, 8)
PRV_WEEK_HI = dt.date(2026, 6, 14)

REP_MONTH_LO = dt.date(2026, 5, 1)
REP_MONTH_HI = dt.date(2026, 5, 31)
PRV_MONTH_LO = dt.date(2026, 4, 1)
PRV_MONTH_HI = dt.date(2026, 4, 30)

KM = KM_PER_MILE  # 1.609344


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_settings(sm, *, currency="GBP", distance_unit="mi"):
    async with sm() as s:
        for key, val in [("currency", currency), ("distance_unit", distance_unit)]:
            existing = (
                await s.execute(select(Setting).where(Setting.key == key))
            ).scalar_one_or_none()
            if existing:
                existing.value = val
            else:
                s.add(
                    Setting(
                        key=key,
                        value=val,
                        value_type="string",
                        group_name="display",
                        label=key,
                        description="",
                        default_value=val,
                    )
                )
        await s.commit()


async def _mk_session(
    sm,
    *,
    user_id,
    car_id,
    when: dt.date,
    kwh: float,
    cost_pence,
    ctype="ac",
    odometer_km=None,
):
    async with sm() as s:
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=when,
                start_soc=20,
                end_soc=80,
                kwh_added=kwh,
                charging_type=ctype,
                charging_mode="manual",
                cost_pence=cost_pence,
                cost_basis="home_rate" if cost_pence is not None else "unknown",
                source="manual",
                odometer_at_session_km=odometer_km,
                charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC),
            )
        )
        await s.commit()


async def _add_car(sm, *, user_id, name="Born", active=True) -> int:
    async with sm() as s:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Born",
            name=name,
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=active,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


async def _add_mileage_year(
    sm,
    *,
    user_id,
    car_id,
    start: dt.date,
    opening_km: float,
    target_km: float,
):
    end = dt.date(start.year + 1, start.month, start.day) - dt.timedelta(days=1)
    async with sm() as s:
        s.add(
            CarMileageYear(
                user_id=user_id,
                car_id=car_id,
                period_start_date=start,
                period_end_date=end,
                opening_odometer_km=opening_km,
                closing_odometer_km=None,
                annual_mileage_target_km=target_km,
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# _delta_phrase
# ---------------------------------------------------------------------------


def test_delta_phrase_down():
    assert _delta_phrase(92.0, 100.0) == "down 8%"


def test_delta_phrase_up():
    assert _delta_phrase(103.0, 100.0) == "up 3%"


def test_delta_phrase_flat():
    assert _delta_phrase(100.0, 100.0) == "flat"


def test_delta_phrase_small_rounds_to_flat():
    # 0.4% rounds to 0 → flat
    assert _delta_phrase(100.4, 100.0) == "flat"


def test_delta_phrase_prev_zero():
    # When prev==0 the comparison is undefined; returns "" so callers omit the parenthetical.
    assert _delta_phrase(50.0, 0.0) == ""


def test_delta_phrase_both_zero():
    # Both zero is also prev==0; same contract: empty string.
    assert _delta_phrase(0.0, 0.0) == ""


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_none_when_empty(test_sessionmaker, seeded_user_car):
    """Returns None when the reported week has zero sessions."""
    user_id, _ = seeded_user_car
    await _seed_settings(test_sessionmaker)
    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)
    assert result is None


@pytest.mark.asyncio
async def test_weekly_correct_window(test_sessionmaker, seeded_user_car):
    """Session in reported week is counted; session outside is not."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # Session IN the reported week (Mon 15 Jun)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=20.0,
        cost_pence=300,
    )
    # Session OUTSIDE (day after the window)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_HI + dt.timedelta(days=1),
        kwh=5.0,
        cost_pence=100,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # Should mention £3.00 (300p) not £1.00
    assert "£3.00" in result


@pytest.mark.asyncio
async def test_weekly_no_home_public_line(test_sessionmaker, seeded_user_car):
    """Weekly digest must NOT contain a Home/public split line."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=20.0,
        cost_pence=300,
        ctype="ac",
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "Home/public" not in result
    assert "home/public" not in result.lower()


@pytest.mark.asyncio
async def test_weekly_delta_vs_prev_week(test_sessionmaker, seeded_user_car):
    """Delta lines compare the reported week to the previous week."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # Previous week: 100p spend, 10 kWh
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=PRV_WEEK_LO,
        kwh=10.0,
        cost_pence=100,
    )
    # Reported week: 200p spend, 20 kWh  (up 100%)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=20.0,
        cost_pence=200,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # Spend went up 100%
    assert "up 100%" in result


@pytest.mark.asyncio
async def test_weekly_has_header(test_sessionmaker, seeded_user_car):
    """Weekly digest must have a header line with the week dates or 'recap'."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=150,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    lines = result.strip().splitlines()
    assert len(lines) >= 3
    # Header should be on the first non-empty line
    header = lines[0]
    assert "📊" in header or "recap" in header.lower() or "week" in header.lower()


@pytest.mark.asyncio
async def test_weekly_per_car_pace_line(test_sessionmaker, seeded_user_car):
    """Per active car, a mileage-pace verdict line appears with display_name."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=150,
        odometer_km=10100.0,
    )

    # Set up mileage tracking: period started 2026-01-01, opening 10000 km,
    # target 16093 km (~10000 mi).
    await _add_mileage_year(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        start=dt.date(2026, 1, 1),
        opening_km=10000.0,
        target_km=16093.44,  # 10000 miles
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # "Born" is the display_name (model) from the seeded_user_car fixture
    assert "Born" in result
    # Should contain pace verdict
    lower = result.lower()
    assert any(word in lower for word in ("on track", "ahead", "behind", "target"))


@pytest.mark.asyncio
async def test_weekly_pace_no_target_omitted_or_noted(test_sessionmaker, seeded_user_car):
    """When no mileage tracking, pace line either omitted or says 'no target'."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=150,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    # Either the car name appears (with a "no target" note) or it's omitted entirely
    # — either is acceptable; just must not crash
    assert result is not None


@pytest.mark.asyncio
async def test_weekly_miles_in_user_unit(test_sessionmaker, seeded_user_car):
    """Miles line honours distance_unit setting (test with 'mi')."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker, distance_unit="mi")

    # Plant odometer readings: 100 km driven in the reported window
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=PRV_WEEK_HI,
        kwh=5.0,
        cost_pence=50,
        odometer_km=10000.0,
    )  # anchor before window
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=150,
        odometer_km=10100.0,
    )  # +100 km in window

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # 100 km ≈ 62 mi; should show "mi" not "km"
    assert " mi" in result
    assert " km" not in result


@pytest.mark.asyncio
async def test_weekly_inactive_car_excluded_from_pace(test_sessionmaker, seeded_user_car):
    """Inactive cars must not produce pace lines."""
    user_id, car_id = seeded_user_car  # this is the active car

    # Add an inactive car
    inactive_id = await _add_car(test_sessionmaker, user_id=user_id, name="OldCar", active=False)
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=150,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "OldCar" not in result


# ---------------------------------------------------------------------------
# Monthly digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monthly_none_when_empty(test_sessionmaker, seeded_user_car):
    """Returns None when the reported month has zero sessions."""
    user_id, _ = seeded_user_car
    await _seed_settings(test_sessionmaker)
    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)
    assert result is None


@pytest.mark.asyncio
async def test_monthly_correct_window(test_sessionmaker, seeded_user_car):
    """Sessions in May 2026 (reported month) are included; April and June are not."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # May session → included
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 15),
        kwh=20.0,
        cost_pence=400,
    )
    # April session → excluded (previous window, used only for delta)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 4, 20),
        kwh=5.0,
        cost_pence=100,
    )
    # June session → excluded from reported month entirely
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 6, 1),
        kwh=8.0,
        cost_pence=200,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "£4.00" in result  # 400p from May only


@pytest.mark.asyncio
async def test_monthly_has_home_public_line(test_sessionmaker, seeded_user_car):
    """Monthly digest MUST contain a Home/public split line."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # May: one AC (home) and one DC (public) charge
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 10),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 20),
        kwh=30.0,
        cost_pence=600,
        ctype="dc",
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    lower = result.lower()
    assert "home" in lower and "public" in lower


@pytest.mark.asyncio
async def test_monthly_header_mentions_month(test_sessionmaker, seeded_user_car):
    """Header should reference 'May' or the month name."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 15),
        kwh=10.0,
        cost_pence=200,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "May" in result or "may" in result.lower()


@pytest.mark.asyncio
async def test_monthly_delta_vs_prev_month(test_sessionmaker, seeded_user_car):
    """Delta lines compare May vs April."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # April: 100p
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 4, 15),
        kwh=10.0,
        cost_pence=100,
    )
    # May: 200p (up 100%)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 15),
        kwh=20.0,
        cost_pence=200,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "up 100%" in result


@pytest.mark.asyncio
async def test_monthly_per_car_pace(test_sessionmaker, seeded_user_car):
    """Monthly digest includes per-car pace verdict."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 15),
        kwh=10.0,
        cost_pence=200,
    )

    await _add_mileage_year(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        start=dt.date(2026, 1, 1),
        opening_km=10000.0,
        target_km=16093.44,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "Born" in result


@pytest.mark.asyncio
async def test_monthly_multi_car_totals_aggregate(test_sessionmaker, seeded_user_car):
    """Totals aggregate across all active cars; each car with tracking gets a pace line."""
    user_id, car_id1 = seeded_user_car
    car_id2 = await _add_car(test_sessionmaker, user_id=user_id, name="Leaf")

    await _seed_settings(test_sessionmaker)

    # Car1: 200p in May
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id1,
        when=dt.date(2026, 5, 10),
        kwh=10.0,
        cost_pence=200,
    )
    # Car2: 300p in May
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id2,
        when=dt.date(2026, 5, 20),
        kwh=15.0,
        cost_pence=300,
    )

    # Enable mileage tracking on both cars
    await _add_mileage_year(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id1,
        start=dt.date(2026, 1, 1),
        opening_km=10000.0,
        target_km=16093.44,
    )
    await _add_mileage_year(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id2,
        start=dt.date(2026, 1, 1),
        opening_km=20000.0,
        target_km=16093.44,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # Total should be 500p = £5.00
    assert "£5.00" in result
    # Both car names should appear in pace section
    assert "Born" in result
    assert "Leaf" in result


@pytest.mark.asyncio
async def test_monthly_home_public_percentages(test_sessionmaker, seeded_user_car):
    """Home/public split shows percentages of spend that sum correctly."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # 200p AC (home), 600p DC (public) → 800p total; 25% home, 75% public
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 10),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 5, 20),
        kwh=30.0,
        cost_pence=600,
        ctype="dc",
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    # Should show 25% home and 75% public
    assert "25%" in result
    assert "75%" in result


@pytest.mark.asyncio
async def test_weekly_flat_when_same_spend(test_sessionmaker, seeded_user_car):
    """When spend is identical week over week, delta is 'flat'."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    for week_lo in (PRV_WEEK_LO, REP_WEEK_LO):
        await _mk_session(
            test_sessionmaker,
            user_id=user_id,
            car_id=car_id,
            when=week_lo,
            kwh=10.0,
            cost_pence=200,
        )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "flat" in result


@pytest.mark.asyncio
async def test_weekly_down_delta(test_sessionmaker, seeded_user_car):
    """When spend drops, the delta says 'down N%'."""
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    # Previous: 200p; reported: 100p → down 50%
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=PRV_WEEK_LO,
        kwh=20.0,
        cost_pence=200,
    )
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=REP_WEEK_LO,
        kwh=10.0,
        cost_pence=100,
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=NOW)

    assert result is not None
    assert "down 50%" in result


# ---------------------------------------------------------------------------
# Year/month boundary tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_year_boundary(test_sessionmaker, seeded_user_car):
    """Reported week crosses a year boundary into the prior December.

    now = 2027-01-03 (Sunday of week 0 of 2027).
    This week's Monday = 2026-12-28.
    Reported (previous Mon-Sun) week = 2026-12-21..2026-12-27.
    Previous-previous week (for delta) = 2026-12-14..2026-12-20.

    If _reported_week regressed to using now.year it would look at Jan 2027,
    finding no sessions, and return None. This test locks the Dec 2026 window.
    """
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    now_boundary = dt.datetime(2027, 1, 3, 9, 0, 0, tzinfo=dt.UTC)

    # Reported week: 2026-12-21 to 2026-12-27
    rep_lo = dt.date(2026, 12, 21)
    prv_lo = dt.date(2026, 12, 14)

    # Seed: 200p in the reported (Dec) week; 100p in the prior week (for delta)
    await _mk_session(
        test_sessionmaker, user_id=user_id, car_id=car_id, when=rep_lo, kwh=20.0, cost_pence=200
    )
    await _mk_session(
        test_sessionmaker, user_id=user_id, car_id=car_id, when=prv_lo, kwh=10.0, cost_pence=100
    )

    async with test_sessionmaker() as s:
        result = await build_weekly_digest(s, user_id=user_id, now=now_boundary)

    # Must not be None (would be None if it looked at the January week instead)
    assert result is not None
    # Reported week spend = £2.00 (200p); NOT £1.00 (100p from prior week)
    assert "£2.00" in result
    # Header must mention December or the 21st
    assert "Dec" in result or "21" in result
    # Delta: 200p vs 100p → up 100%
    assert "up 100%" in result


@pytest.mark.asyncio
async def test_monthly_january_boundary(test_sessionmaker, seeded_user_car):
    """Reported month crosses a year boundary: now in Jan 2027 → reported = Dec 2026.

    now = 2027-01-15.
    Reported month = December 2026 (2026-12-01 to 2026-12-31).
    Previous month = November 2026 (2026-11-01 to 2026-11-30).

    If _reported_month regressed to now.month/year it would look at January 2027,
    finding no sessions, and return None. This test locks the December window.
    """
    user_id, car_id = seeded_user_car
    await _seed_settings(test_sessionmaker)

    now_boundary = dt.datetime(2027, 1, 15, 9, 0, 0, tzinfo=dt.UTC)

    # Dec 2026 (reported): 400p spend
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 12, 15),
        kwh=20.0,
        cost_pence=400,
    )
    # Nov 2026 (previous, for delta): 200p spend
    await _mk_session(
        test_sessionmaker,
        user_id=user_id,
        car_id=car_id,
        when=dt.date(2026, 11, 15),
        kwh=10.0,
        cost_pence=200,
    )

    async with test_sessionmaker() as s:
        result = await build_monthly_digest(s, user_id=user_id, now=now_boundary)

    # Must not be None (would be None if it looked at January 2027 instead)
    assert result is not None
    # Header must reference December
    assert "December" in result or "Dec" in result
    # Reported spend = £4.00 (Dec); NOT £2.00 (Nov)
    assert "£4.00" in result
    # Delta: 400p vs 200p → up 100%
    assert "up 100%" in result
