"""Tests for ownership_trends.py aggregators (Task 1).

TDD: tests written first (RED), then implementation made them GREEN.

Season mapping (documented here for reference):
  winter = Dec, Jan, Feb
  spring = Mar, Apr, May
  summer = Jun, Jul, Aug
  autumn = Sep, Oct, Nov

seasonal_delta simplification: best vs worst month by mi_per_kwh once ≥2
non-None points exist in *different calendar months* (no season-labelling
required for the delta; seasons are conceptual documentation).

Qualifying charge threshold: (end_soc - start_soc) >= 40 (percentage points).
low_confidence for capacity_trend: AC charges OR total qualifying < 3.
current_estimated_capacity: rolling median of most recent N=10 qualifying,
preferring DC when ≥3 DC qualifying charges exist, else falls back to all qualifying.
"""
from __future__ import annotations

import datetime as dt
import statistics

import pytest

from plugtrack.models import ChargingSession
from plugtrack.services.mileage_tracking import KM_PER_MILE


async def _mk(
    sm,
    *,
    user_id,
    car_id,
    when: dt.date,
    kwh: float,
    cost_pence=None,
    start_soc: int = 20,
    end_soc: int = 80,
    ctype: str = "ac",
    odometer_km: float | None = None,
):
    """Seed one ChargingSession. Mirroring the _mk helper in test_insights_stats."""
    async with sm() as s:
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=when,
                start_soc=start_soc,
                end_soc=end_soc,
                kwh_added=kwh,
                charging_type=ctype,
                charging_mode="manual",
                cost_pence=cost_pence,
                cost_basis="home_rate" if cost_pence is not None else "unknown",
                source="manual",
                odometer_at_session_km=odometer_km,
                charge_end_at=dt.datetime.combine(
                    when, dt.time(12, 0), tzinfo=dt.timezone.utc
                ),
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# efficiency_by_month
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_efficiency_by_month_basic(test_sessionmaker, seeded_user_car):
    """Two months of data: correct mi/kWh, derived_range_km, period keys.

    The miles_driven_km helper uses the max odometer BEFORE the window as
    the start anchor (date <= lo - 1day). So the anchor session must live in
    the month PRIOR to the window being tested.
    """
    uid, car = seeded_user_car
    battery_kwh = 58.0

    # December anchor (before Jan window): 1000 km
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2025, 12, 31), kwh=1.0, odometer_km=1000.0,
    )
    # January sessions: two so it's not sparse; end odo = 1000 + 100 mi
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 10), kwh=12.5, odometer_km=1000.0 + 50 * KM_PER_MILE,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 20), kwh=12.5, odometer_km=1000.0 + 100 * KM_PER_MILE,
    )

    # February sessions: two, driven +50 mi more (anchor = Jan 20 odo)
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 2, 5), kwh=10.0, odometer_km=1000.0 + 120 * KM_PER_MILE,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 2, 20), kwh=10.0, odometer_km=1000.0 + 150 * KM_PER_MILE,
    )

    from plugtrack.services.ownership_trends import efficiency_by_month

    async with test_sessionmaker() as s:
        pts = await efficiency_by_month(s, user_id=uid, car_id=car, battery_kwh=battery_kwh)

    # Should have Jan and Feb points (Dec anchor has a session but is its own month)
    periods = [p["period"] for p in pts]
    assert "2026-01" in periods
    assert "2026-02" in periods

    jan = next(p for p in pts if p["period"] == "2026-01")
    # Cycle-based: two Jan cycles drive 50+50=100 mi; each consumes the SoC drop
    # (80%→20% = 60% of 58 kWh = 34.8 kWh, ×2 = 69.6) → 100/69.6 = 1.44 mi/kWh.
    assert jan["mi_per_kwh"] == pytest.approx(100 / 69.6, abs=0.02)
    expected_range = jan["mi_per_kwh"] * battery_kwh * KM_PER_MILE
    assert jan["derived_range_km"] == pytest.approx(expected_range, abs=0.5)
    assert "low_confidence" in jan


@pytest.mark.asyncio
async def test_efficiency_by_month_low_confidence_sparse(test_sessionmaker, seeded_user_car):
    """A month with only 1 session is low_confidence=True."""
    uid, car = seeded_user_car

    # Anchor before Jan
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2025, 12, 31), kwh=1.0, odometer_km=500.0,
    )
    # Single session in Jan
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 10), kwh=15.0, odometer_km=600.0,
    )

    from plugtrack.services.ownership_trends import efficiency_by_month

    async with test_sessionmaker() as s:
        pts = await efficiency_by_month(s, user_id=uid, car_id=car, battery_kwh=58.0)

    jan = next((p for p in pts if p["period"] == "2026-01"), None)
    assert jan is not None
    assert jan["low_confidence"] is True


@pytest.mark.asyncio
async def test_efficiency_by_month_no_odometer_is_none(test_sessionmaker, seeded_user_car):
    """Month with sessions but no odometer → mi_per_kwh=None, low_confidence=True."""
    uid, car = seeded_user_car

    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 3, 1), kwh=20.0, odometer_km=None,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 3, 15), kwh=20.0, odometer_km=None,
    )

    from plugtrack.services.ownership_trends import efficiency_by_month

    async with test_sessionmaker() as s:
        pts = await efficiency_by_month(s, user_id=uid, car_id=car, battery_kwh=58.0)

    mar = next((p for p in pts if p["period"] == "2026-03"), None)
    assert mar is not None
    assert mar["mi_per_kwh"] is None
    assert mar["derived_range_km"] is None
    assert mar["low_confidence"] is True


@pytest.mark.asyncio
async def test_efficiency_by_month_per_car_isolation(test_sessionmaker, seeded_user_car):
    """Sessions from another car must not bleed into the result."""
    uid, car1 = seeded_user_car
    from plugtrack.models import Car

    async with test_sessionmaker() as s:
        car2_obj = Car(
            user_id=uid, make="T", model="M", battery_kwh=40.0,
            nominal_efficiency_mi_per_kwh=3.5, provider="manual", active=True,
        )
        s.add(car2_obj)
        await s.commit()
        await s.refresh(car2_obj)
        car2 = car2_obj.id

    # car2 only
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car2,
        when=dt.date(2026, 4, 10), kwh=30.0, odometer_km=2000.0,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car2,
        when=dt.date(2026, 4, 20), kwh=30.0, odometer_km=2200.0,
    )

    from plugtrack.services.ownership_trends import efficiency_by_month

    async with test_sessionmaker() as s:
        pts_car1 = await efficiency_by_month(s, user_id=uid, car_id=car1, battery_kwh=58.0)

    # car1 has no sessions → empty list
    assert pts_car1 == []


@pytest.mark.asyncio
async def test_efficiency_by_month_empty_no_sessions(test_sessionmaker, seeded_user_car):
    """No sessions at all → empty list."""
    uid, car = seeded_user_car

    from plugtrack.services.ownership_trends import efficiency_by_month

    async with test_sessionmaker() as s:
        pts = await efficiency_by_month(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert pts == []


# ---------------------------------------------------------------------------
# seasonal_delta
# ---------------------------------------------------------------------------


def test_seasonal_delta_none_with_one_point():
    """Single point → None."""
    from plugtrack.services.ownership_trends import seasonal_delta

    pts = [{"period": "2026-01", "mi_per_kwh": 3.5, "derived_range_km": 200.0, "low_confidence": False}]
    assert seasonal_delta(pts) is None


def test_seasonal_delta_none_with_one_non_none():
    """Two points but only one has non-None mi_per_kwh → None."""
    from plugtrack.services.ownership_trends import seasonal_delta

    pts = [
        {"period": "2026-01", "mi_per_kwh": 3.5, "derived_range_km": 200.0, "low_confidence": False},
        {"period": "2026-02", "mi_per_kwh": None, "derived_range_km": None, "low_confidence": True},
    ]
    assert seasonal_delta(pts) is None


def test_seasonal_delta_best_vs_worst_two_months():
    """Two months with values in different months → best/worst/pct/abs."""
    from plugtrack.services.ownership_trends import seasonal_delta

    pts = [
        {"period": "2026-01", "mi_per_kwh": 3.0, "derived_range_km": 174.0, "low_confidence": False},
        {"period": "2026-07", "mi_per_kwh": 4.5, "derived_range_km": 261.0, "low_confidence": False},
    ]
    result = seasonal_delta(pts)
    assert result is not None
    assert result["best"]["period"] == "2026-07"
    assert result["worst"]["period"] == "2026-01"
    expected_pct = (4.5 - 3.0) / 3.0 * 100
    assert result["pct"] == pytest.approx(expected_pct, abs=0.1)
    assert result["abs_mi_per_kwh"] == pytest.approx(4.5 - 3.0, abs=0.001)


def test_seasonal_delta_same_month_two_points():
    """Two points in the same calendar month (e.g. different years) → should still work
    as we only require different periods."""
    from plugtrack.services.ownership_trends import seasonal_delta

    pts = [
        {"period": "2025-06", "mi_per_kwh": 4.0, "derived_range_km": 232.0, "low_confidence": False},
        {"period": "2026-06", "mi_per_kwh": 3.8, "derived_range_km": 220.0, "low_confidence": False},
    ]
    result = seasonal_delta(pts)
    assert result is not None
    assert result["best"]["period"] == "2025-06"
    assert result["worst"]["period"] == "2026-06"


def test_seasonal_delta_ignores_none_mi_per_kwh():
    """Points with None mi_per_kwh are excluded from best/worst selection."""
    from plugtrack.services.ownership_trends import seasonal_delta

    pts = [
        {"period": "2026-01", "mi_per_kwh": 3.0, "derived_range_km": 174.0, "low_confidence": False},
        {"period": "2026-04", "mi_per_kwh": None, "derived_range_km": None, "low_confidence": True},
        {"period": "2026-07", "mi_per_kwh": 4.5, "derived_range_km": 261.0, "low_confidence": False},
    ]
    result = seasonal_delta(pts)
    assert result is not None
    assert result["best"]["period"] == "2026-07"
    assert result["worst"]["period"] == "2026-01"


# ---------------------------------------------------------------------------
# capacity_trend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_trend_qualifying_filter(test_sessionmaker, seeded_user_car):
    """30% SoC delta is excluded; 50% delta is included."""
    uid, car = seeded_user_car

    # NON-qualifying: 30% delta
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 2, 1), kwh=17.4, ctype="dc",
        start_soc=50, end_soc=80,  # only 30% delta → excluded
    )

    # QUALIFYING: 50% delta, 29 kWh → usable = 29 / 0.50 = 58.0
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 3, 1), kwh=29.0, ctype="dc",
        start_soc=20, end_soc=70,  # 50% delta → included
    )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert len(pts) == 1
    assert pts[0]["date"] == "2026-03-01"
    assert pts[0]["usable_kwh"] == pytest.approx(58.0, abs=0.01)
    assert pts[0]["charging_type"] == "dc"


@pytest.mark.asyncio
async def test_capacity_trend_usable_kwh_formula(test_sessionmaker, seeded_user_car):
    """usable_kwh = kwh_added / ((end_soc - start_soc) / 100)."""
    uid, car = seeded_user_car

    # 29 kWh over 50% delta → 58.0
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 5, 10), kwh=29.0, ctype="dc",
        start_soc=10, end_soc=60,  # 50% delta
    )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert len(pts) == 1
    assert pts[0]["usable_kwh"] == pytest.approx(58.0, abs=0.01)


@pytest.mark.asyncio
async def test_capacity_trend_ac_is_low_confidence(test_sessionmaker, seeded_user_car):
    """AC charges are low_confidence=True regardless of delta size."""
    uid, car = seeded_user_car

    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 4, 5), kwh=29.0, ctype="ac",
        start_soc=10, end_soc=60,
    )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert len(pts) == 1
    assert pts[0]["charging_type"] == "ac"
    assert pts[0]["low_confidence"] is True


@pytest.mark.asyncio
async def test_capacity_trend_dc_few_is_low_confidence(test_sessionmaker, seeded_user_car):
    """DC with fewer than 3 total qualifying charges → low_confidence=True."""
    uid, car = seeded_user_car

    # Only 2 qualifying DC charges total
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 4, 1), kwh=29.0, ctype="dc",
        start_soc=10, end_soc=60,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 4, 2), kwh=28.0, ctype="dc",
        start_soc=15, end_soc=65,
    )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    # All should be low_confidence because total qualifying < 3
    assert len(pts) == 2
    assert all(p["low_confidence"] is True for p in pts)


@pytest.mark.asyncio
async def test_capacity_trend_dc_3_or_more_not_low_confidence(test_sessionmaker, seeded_user_car):
    """DC with ≥3 total qualifying charges → low_confidence=False for DC entries."""
    uid, car = seeded_user_car

    for i in range(3):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 5, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert len(pts) == 3
    assert all(p["low_confidence"] is False for p in pts)


@pytest.mark.asyncio
async def test_capacity_trend_excludes_zero_kwh(test_sessionmaker, seeded_user_car):
    """kwh_added=0 is non-qualifying even with a large soc delta."""
    uid, car = seeded_user_car

    # kwh=0 → should be excluded
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 6, 1), kwh=0.0, ctype="dc",
        start_soc=10, end_soc=80,
    )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert pts == []


@pytest.mark.asyncio
async def test_capacity_trend_ordered_by_date(test_sessionmaker, seeded_user_car):
    """Points are returned in ascending date order."""
    uid, car = seeded_user_car

    dates = [dt.date(2026, 3, 15), dt.date(2026, 1, 5), dt.date(2026, 2, 20)]
    for d in dates:
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=d, kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import capacity_trend

    async with test_sessionmaker() as s:
        pts = await capacity_trend(s, user_id=uid, car_id=car, battery_kwh=58.0)

    actual_dates = [p["date"] for p in pts]
    assert actual_dates == sorted(actual_dates)


# ---------------------------------------------------------------------------
# current_estimated_capacity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_estimated_capacity_none_when_no_qualifying(test_sessionmaker, seeded_user_car):
    """No qualifying charges → None."""
    uid, car = seeded_user_car

    from plugtrack.services.ownership_trends import current_estimated_capacity

    async with test_sessionmaker() as s:
        result = await current_estimated_capacity(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert result is None


@pytest.mark.asyncio
async def test_current_estimated_capacity_dc_preferred(test_sessionmaker, seeded_user_car):
    """When ≥3 DC qualifying charges, prefer them over AC."""
    uid, car = seeded_user_car

    # 3 DC charges: usable_kwh = 58.0 each
    for i in range(3):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 6, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    # 2 AC charges: usable_kwh = 60.0 each (should be ignored when DC preferred)
    for i in range(2):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 7, i + 1), kwh=30.0, ctype="ac",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import current_estimated_capacity

    async with test_sessionmaker() as s:
        result = await current_estimated_capacity(s, user_id=uid, car_id=car, battery_kwh=58.0)

    # DC median: 58.0 (all DC usable=58)
    assert result == pytest.approx(58.0, abs=0.1)


@pytest.mark.asyncio
async def test_current_estimated_capacity_fallback_to_ac(test_sessionmaker, seeded_user_car):
    """When < 3 DC qualifying charges, fall back to all qualifying."""
    uid, car = seeded_user_car

    # Only 2 DC qualifying
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 6, 1), kwh=29.0, ctype="dc",
        start_soc=10, end_soc=60,  # usable=58
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 6, 2), kwh=28.0, ctype="dc",
        start_soc=10, end_soc=60,  # usable=56
    )
    # 1 AC qualifying
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 7, 1), kwh=30.0, ctype="ac",
        start_soc=10, end_soc=60,  # usable=60
    )

    from plugtrack.services.ownership_trends import current_estimated_capacity

    async with test_sessionmaker() as s:
        result = await current_estimated_capacity(s, user_id=uid, car_id=car, battery_kwh=58.0)

    # All 3 qualifying: usable = [58, 56, 60] → median = 58
    usables = sorted([58.0, 56.0, 60.0])
    expected = statistics.median(usables)
    assert result == pytest.approx(expected, abs=0.1)


@pytest.mark.asyncio
async def test_current_estimated_capacity_rolling_median(test_sessionmaker, seeded_user_car):
    """Rolling median of the most recent N qualifying charges."""
    uid, car = seeded_user_car

    # Seed 12 DC charges: first 2 with usable=40, then 10 with usable=58
    # The rolling window (N=10) should capture only the recent 10 (usable=58)
    for i in range(2):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2025, 1, i + 1), kwh=20.0, ctype="dc",
            start_soc=10, end_soc=60,  # usable=40
        )
    for i in range(10):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 3, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,  # usable=58
        )

    from plugtrack.services.ownership_trends import current_estimated_capacity

    async with test_sessionmaker() as s:
        result = await current_estimated_capacity(s, user_id=uid, car_id=car, battery_kwh=58.0)

    # Only most recent 10 DC qualifying → all usable=58 → median=58
    assert result == pytest.approx(58.0, abs=0.1)


# ---------------------------------------------------------------------------
# battery_health_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_battery_health_none_when_no_battery_kwh(test_sessionmaker, seeded_user_car):
    """battery_kwh of 0 or None → None (no nominal to compare against)."""
    uid, car = seeded_user_car

    # A qualifying charge exists, but battery_kwh is invalid.
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 5, 1), kwh=29.0, ctype="dc",
        start_soc=10, end_soc=60,
    )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        assert await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=0) is None
        assert await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=None) is None


@pytest.mark.asyncio
async def test_battery_health_none_when_no_qualifying(test_sessionmaker, seeded_user_car):
    """No qualifying charges → None (estimator returns None)."""
    uid, car = seeded_user_car

    # Non-qualifying charge (30% delta only).
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 5, 1), kwh=17.4, ctype="dc",
        start_soc=50, end_soc=80,
    )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        result = await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert result is None


@pytest.mark.asyncio
async def test_battery_health_happy_path(test_sessionmaker, seeded_user_car):
    """3 DC qualifying charges, usable=57 each, nominal=60 → soh 95%."""
    uid, car = seeded_user_car
    battery_kwh = 60.0

    # 3 DC charges: 28.5 kWh over 50% delta → usable_kwh = 57.0 each.
    for i in range(3):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 6, i + 1), kwh=28.5, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        result = await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=battery_kwh)

    assert result is not None
    assert result["estimated_usable_kwh"] == pytest.approx(57.0, abs=0.01)
    assert result["nominal_kwh"] == 60.0
    assert result["soh_pct"] == 95
    assert result["soh_pct_raw"] == 95
    assert result["qualifying_count"] == 3
    assert result["low_confidence"] is False


@pytest.mark.asyncio
async def test_battery_health_caps_soh_at_100(test_sessionmaker, seeded_user_car):
    """Implied usable capacity above nominal → soh_pct capped at 100, raw > 100."""
    uid, car = seeded_user_car
    battery_kwh = 50.0

    # 3 DC charges: 29 kWh over 50% delta → usable_kwh = 58.0 each (> 50 nominal).
    for i in range(3):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 6, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        result = await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=battery_kwh)

    assert result is not None
    # raw = 58 / 50 * 100 = 116
    assert result["soh_pct"] == 100
    assert result["soh_pct_raw"] == 116
    assert result["soh_pct_raw"] > 100


@pytest.mark.asyncio
async def test_battery_health_low_confidence_below_threshold(test_sessionmaker, seeded_user_car):
    """Fewer than 3 qualifying charges → low_confidence=True."""
    uid, car = seeded_user_car

    # Only 2 qualifying charges.
    for i in range(2):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 6, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        result = await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert result is not None
    assert result["qualifying_count"] == 2
    assert result["low_confidence"] is True


@pytest.mark.asyncio
async def test_battery_health_low_confidence_false_at_threshold(test_sessionmaker, seeded_user_car):
    """3 or more qualifying charges → low_confidence=False."""
    uid, car = seeded_user_car

    for i in range(3):
        await _mk(
            test_sessionmaker, user_id=uid, car_id=car,
            when=dt.date(2026, 6, i + 1), kwh=29.0, ctype="dc",
            start_soc=10, end_soc=60,
        )

    from plugtrack.services.ownership_trends import battery_health_summary

    async with test_sessionmaker() as s:
        result = await battery_health_summary(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert result is not None
    assert result["qualifying_count"] == 3
    assert result["low_confidence"] is False


# ---------------------------------------------------------------------------
# seasonal_range_span
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seasonal_range_span_none_no_data(test_sessionmaker, seeded_user_car):
    """No sessions → None."""
    uid, car = seeded_user_car

    from plugtrack.services.ownership_trends import seasonal_range_span

    async with test_sessionmaker() as s:
        result = await seasonal_range_span(s, user_id=uid, car_id=car, battery_kwh=58.0)

    assert result is None


@pytest.mark.asyncio
async def test_seasonal_range_span_min_max_avg(test_sessionmaker, seeded_user_car):
    """min/max/avg over months with non-None derived_range_km.

    Anchors must be in the month BEFORE the window under test (how
    miles_driven_km resolves start = max(odo WHERE date <= lo-1)).
    """
    uid, car = seeded_user_car
    battery_kwh = 58.0

    # Dec 2025 anchor (before Jan window)
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2025, 12, 31), kwh=1.0, odometer_km=1000.0,
    )
    # Jan: two sessions, +100 mi → 4.0 mi/kWh
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 10), kwh=12.5, odometer_km=1000.0 + 50 * KM_PER_MILE,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 20), kwh=12.5, odometer_km=1000.0 + 100 * KM_PER_MILE,
    )

    # Feb anchor (before Mar window): last Jan odo is the anchor
    # March: two sessions, +50 mi → 2.5 mi/kWh (20 kWh total)
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 3, 5), kwh=10.0, odometer_km=1000.0 + 120 * KM_PER_MILE,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 3, 20), kwh=10.0, odometer_km=1000.0 + 150 * KM_PER_MILE,
    )
    # Feb has no sessions so the March window anchor = Jan 20 odo (1000+100mi km)
    # Mar driven = (1000+150mi) - (1000+100mi) = 50 mi; kwh=20 → 2.5 mi/kWh

    from plugtrack.services.ownership_trends import seasonal_range_span

    async with test_sessionmaker() as s:
        result = await seasonal_range_span(s, user_id=uid, car_id=car, battery_kwh=battery_kwh)

    assert result is not None
    # Cycle-based mi/kWh: each cycle consumes 60% of 58 kWh = 34.8 kWh.
    # Jan drives 100 mi / 69.6 kWh; Mar drives 50 mi / 69.6 kWh.
    range_jan = (100 / 69.6) * battery_kwh * KM_PER_MILE
    range_mar = (50 / 69.6) * battery_kwh * KM_PER_MILE
    assert result["min_km"] == pytest.approx(min(range_jan, range_mar), abs=0.5)
    assert result["max_km"] == pytest.approx(max(range_jan, range_mar), abs=0.5)
    assert result["avg_km"] == pytest.approx((range_jan + range_mar) / 2, abs=0.5)


@pytest.mark.asyncio
async def test_seasonal_range_span_skips_none_months(test_sessionmaker, seeded_user_car):
    """Months without odometer (range=None) are excluded from min/max/avg.

    Anchor is in Dec (before the Jan window).
    """
    uid, car = seeded_user_car
    battery_kwh = 58.0

    # Dec anchor before Jan window
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2025, 12, 31), kwh=1.0, odometer_km=1000.0,
    )
    # Jan: two sessions with odometer → 4.0 mi/kWh
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 10), kwh=12.5, odometer_km=1000.0 + 50 * KM_PER_MILE,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 1, 20), kwh=12.5, odometer_km=1000.0 + 100 * KM_PER_MILE,
    )

    # Feb: no odometer → range=None
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 2, 10), kwh=20.0, odometer_km=None,
    )
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car,
        when=dt.date(2026, 2, 20), kwh=20.0, odometer_km=None,
    )

    from plugtrack.services.ownership_trends import seasonal_range_span

    async with test_sessionmaker() as s:
        result = await seasonal_range_span(s, user_id=uid, car_id=car, battery_kwh=battery_kwh)

    assert result is not None
    # Only Jan contributes (Feb has no odometer). Cycle-based: 100 mi / 69.6 kWh.
    expected_range = (100 / 69.6) * battery_kwh * KM_PER_MILE
    assert result["min_km"] == pytest.approx(expected_range, abs=0.5)
    assert result["max_km"] == pytest.approx(expected_range, abs=0.5)
    assert result["avg_km"] == pytest.approx(expected_range, abs=0.5)
