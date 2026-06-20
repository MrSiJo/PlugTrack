"""RED→GREEN tests for two bug fixes in charge_planner.py.

Fix 1 (GATING — divide-by-zero): guard zero-power bands in DC integration.
  - build_dc_capability MUST drop non-positive curve points when pooling band
    points, so a zero/negative power sample never becomes a band median.
  - estimate_scenario DC integration MUST NOT raise ZeroDivisionError when
    capability returns 0 for a band.

Fix 2 (Minor, spec-alignment): car-scope the AC home-actual history.
  - resolve_plan_inputs MUST filter AC home sessions by car_id as well as
    user_id, so the "Your home (actual)" power is per-car.

All DB-backed tests use the shared fixtures (SQLite in tmp_path).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio

from plugtrack.services.charge_planner import (
    DcCapability,
    DcSession,
    build_dc_capability,
    estimate_scenario,
    resolve_plan_inputs,
)


# ---------------------------------------------------------------------------
# Fix 1a — build_dc_capability: zero-power curve points must be dropped
# ---------------------------------------------------------------------------


class TestBuildDcCapabilityDropsZeroPowerPoints:
    """band_points pool must exclude non-positive power_kw values."""

    def test_zero_power_curve_point_not_included_in_band_median(self):
        """A single 0.0-power point in band 50-60 must NOT make the median 0.

        Before the fix: the 0.0 point is pooled → band 50 has [0.0, 100.0]
        → median = 50.0.  After the fix: 0.0 is dropped → band 50 has
        [100.0] → median = 100.0.
        """
        curve = [
            [0, 55, 0.0],    # zero-power point — must be dropped
            [30, 57, 100.0], # good point
        ]
        sess = DcSession(
            start_soc=50,
            end_soc=60,
            kwh_added=5.0,
            actual_charge_seconds=180,
            wall_seconds=200,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[sess],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(55)
        assert tag == "curve"
        # With fix: median([100.0]) == 100.0, well above 0.
        # Without fix: median([0.0, 100.0]) == 50.0 (still non-zero but wrong).
        # The critical assertion is that the zero point was excluded:
        assert power == pytest.approx(100.0, abs=0.1), (
            "zero-power curve point polluted the band median; "
            f"expected 100.0 but got {power:.1f}"
        )

    def test_all_zero_curve_points_in_band_fall_through_to_average(self):
        """If ALL points in a band are zero, that band must NOT get a curve entry.

        Tier 1 (curve) must be absent → tier 2 (average) should respond.
        """
        curve = [
            [0, 55, 0.0],  # zero — dropped
            [30, 58, 0.0], # zero — dropped
        ]
        sess = DcSession(
            start_soc=50,
            end_soc=60,
            kwh_added=5.0,
            actual_charge_seconds=180,  # → 5/(180/3600)=100 kW effective
            wall_seconds=200,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[sess],
            max_dc_kw=150.0,
        )
        _power, tag = cap.power_at(55)
        # After the fix, band 50 has no valid curve points → falls to tier 2
        # (average) because the session overlaps this band.
        assert tag in ("average", "modelled"), (
            f"expected 'average' or 'modelled' but got '{tag}'; "
            "zero curve points should have been dropped from tier-1 pool"
        )

    def test_negative_power_curve_point_not_included(self):
        """Negative power_kw values (data errors) must also be excluded."""
        curve = [
            [0, 35, -5.0],   # negative — must be dropped
            [30, 37, 90.0],  # good
        ]
        sess = DcSession(
            start_soc=30,
            end_soc=40,
            kwh_added=4.0,
            actual_charge_seconds=160,
            wall_seconds=200,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[sess],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(35)
        assert tag == "curve"
        # Negative excluded → median([90.0]) == 90.0, NOT median([-5.0, 90.0]) == 42.5
        assert power == pytest.approx(90.0, abs=0.1), (
            f"negative curve point polluted band median: got {power:.1f}, expected 90.0"
        )


# ---------------------------------------------------------------------------
# Fix 1b — estimate_scenario: must not ZeroDivisionError with zero capability
# ---------------------------------------------------------------------------


class TestEstimateScenarioZeroDivisionGuard:
    """estimate_scenario must be safe when capability returns 0 for a band.

    This guard exists in the integration loop:
        effective_kw = min(charger_cap_kw, cap_kw)
        total_time_h += delta_kwh / (effective_kw * loss_factor)   <- division

    When cap_kw==0 (e.g., all curve points in a band were zero, and there is
    also no average or modelled fallback), effective_kw=0 triggers ZeroDivisionError.
    We replicate a pathological DcCapability that returns 0 for every band.
    """

    @staticmethod
    def _zero_capability() -> DcCapability:
        """Construct a DcCapability that always returns 0 kW for every band."""
        # We directly construct the object with all bands set to 0.0
        # to simulate the pre-fix scenario where zero curve points
        # made it through to band_curve.
        return DcCapability(
            ceiling=100.0,
            band_curve={b: 0.0 for b in range(0, 100, 10)},
            band_average={},
        )

    def test_estimate_scenario_does_not_raise_on_zero_capability(self):
        """estimate_scenario must not raise ZeroDivisionError."""
        cap = self._zero_capability()
        # Before the fix this raises ZeroDivisionError
        try:
            row = estimate_scenario(
                kind="dc",
                label="test",
                start_soc=20,
                target_soc=30,
                battery_kwh=77.0,
                charger_cap_kw=100.0,
                capability=cap,
                flat_power_kw=None,
                loss_factor=0.9,
                ac_window=None,
                source_tag="",
            )
        except ZeroDivisionError:
            pytest.fail(
                "estimate_scenario raised ZeroDivisionError on zero-capability; "
                "Fix 1b guard is missing"
            )

    def test_estimate_scenario_zero_capability_minutes_not_negative(self):
        """With zero-power bands the row must have non-negative minutes."""
        cap = self._zero_capability()
        row = estimate_scenario(
            kind="dc",
            label="test",
            start_soc=20,
            target_soc=30,
            battery_kwh=77.0,
            charger_cap_kw=100.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=0.9,
            ac_window=None,
            source_tag="",
        )
        assert row.minutes >= 0

    def test_estimate_scenario_mixed_zero_and_positive_capability(self):
        """When some bands are zero and some are positive, result is sensible.

        The zero slices are skipped; the positive slices contribute normally.
        """
        # Band 20-29 → 0 kW; band 30-39 → 100 kW
        cap = DcCapability(
            ceiling=100.0,
            band_curve={20: 0.0, 30: 100.0},
            band_average={},
        )
        row = estimate_scenario(
            kind="dc",
            label="test",
            start_soc=20,
            target_soc=40,
            battery_kwh=77.0,
            charger_cap_kw=100.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        # Slices 20-29 are skipped (zero), slices 30-39 contribute 7.7 kWh / 100 kW
        # = 0.077 h = ~4.62 min -> round = 5
        assert row.minutes >= 0
        assert not math.isnan(row.minutes)
        assert not math.isinf(float(row.minutes))


# ---------------------------------------------------------------------------
# Fix 2 — resolve_plan_inputs: AC home query must be car-scoped
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_car_user(test_sessionmaker):
    """Seed: one user, two cars, one home location.

    Car A gets AC home sessions at 7 kW effective.
    Car B gets AC home sessions at 3 kW effective.

    Before Fix 2: resolve_plan_inputs for car A mixes both -> median != 7.
    After Fix 2: resolve_plan_inputs for car A returns ~7 kW.
    """
    from plugtrack.models import Car, ChargingSession, Location, User

    async with test_sessionmaker() as s:
        user = User(username="two_car_user", password_hash="x")
        s.add(user)
        await s.flush()

        car_a = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
            max_ac_kw=None,   # no spec cap -> observed history matters
            max_dc_kw=100.0,
        )
        car_b = Car(
            user_id=user.id,
            make="VW",
            model="ID.3",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
            max_ac_kw=None,
            max_dc_kw=100.0,
        )
        s.add(car_a)
        s.add(car_b)
        await s.flush()

        # Shared home location
        home = Location(
            user_id=user.id,
            centroid_lat=51.5,
            centroid_lng=-0.1,
            is_home=True,
            is_free=False,
            default_cost_per_kwh_p=28.0,
        )
        s.add(home)
        await s.flush()

        def _make_session(car_id, kwh, hours, day_offset):
            """Return a minimal AC home ChargingSession."""
            start = datetime(2026, 1, day_offset, 23, 45, tzinfo=timezone.utc)
            end = start + timedelta(hours=hours)
            return ChargingSession(
                user_id=user.id,
                car_id=car_id,
                date=date(2026, 1, day_offset),
                charging_type="ac",
                start_soc=20,
                end_soc=80,
                kwh_added=kwh,
                charge_start_at=start,
                charge_end_at=end,
                source="manual",
                cost_basis="unknown",
                location_id=home.id,
            )

        # Car A: 3 sessions at ~7 kW (7 kWh / 1 hour each)
        for day in [2, 3, 4]:
            s.add(_make_session(car_a.id, kwh=7.0, hours=1.0, day_offset=day))

        # Car B: 3 sessions at ~3 kW (3 kWh / 1 hour each)
        for day in [5, 6, 7]:
            s.add(_make_session(car_b.id, kwh=3.0, hours=1.0, day_offset=day))

        await s.commit()
        await s.refresh(user)
        await s.refresh(car_a)
        await s.refresh(car_b)
        return user.id, car_a.id, car_b.id


@pytest.mark.asyncio
class TestResolveHomeACCarScoped:
    """Fix 2: resolve_plan_inputs must use car-scoped home AC history."""

    async def test_car_a_power_reflects_only_car_a_sessions(self, test_sessionmaker, two_car_user):
        """Car A's history-based power_kw must be ~7 kW, not diluted by Car B's 3 kW."""
        user_id, car_a_id, _car_b_id = two_car_user

        from plugtrack.models import Car

        async with test_sessionmaker() as s:
            car_a = await s.get(Car, car_a_id)
            inputs = await resolve_plan_inputs(s, car_a, user_id)

        # With Fix 2 (car-scoped): only car A's 7 kW sessions -> median = 7.0
        # Without Fix 2 (user-scoped): mixes car A (7,7,7) + car B (3,3,3) -> median = 5.0
        assert inputs.power_basis == "history", (
            f"expected 'history' (got '{inputs.power_basis}'); "
            "fewer than 3 valid sessions found — check fixture seeding"
        )
        # Strict: median must be ~7 kW (Car A's rate), not ~5 kW (mixed)
        assert inputs.power_kw == pytest.approx(7.0, abs=0.1), (
            f"power_kw={inputs.power_kw:.2f} kW; expected ~7.0 kW (Car A only). "
            "Fix 2 (car_id filter on AC home query) is not applied."
        )

    async def test_car_b_power_reflects_only_car_b_sessions(self, test_sessionmaker, two_car_user):
        """Car B's history-based power_kw must be ~3 kW, not inflated by Car A's 7 kW."""
        user_id, _car_a_id, car_b_id = two_car_user

        from plugtrack.models import Car

        async with test_sessionmaker() as s:
            car_b = await s.get(Car, car_b_id)
            inputs = await resolve_plan_inputs(s, car_b, user_id)

        assert inputs.power_basis == "history"
        assert inputs.power_kw == pytest.approx(3.0, abs=0.1), (
            f"power_kw={inputs.power_kw:.2f} kW; expected ~3.0 kW (Car B only). "
            "Fix 2 (car_id filter on AC home query) is not applied."
        )

    async def test_sample_size_is_per_car_not_combined(self, test_sessionmaker, two_car_user):
        """sample_size must be 3 (per-car sessions), not 6 (combined)."""
        user_id, car_a_id, _car_b_id = two_car_user

        from plugtrack.models import Car

        async with test_sessionmaker() as s:
            car_a = await s.get(Car, car_a_id)
            inputs = await resolve_plan_inputs(s, car_a, user_id)

        # 3 sessions for car A; without fix it would be 6 (both cars)
        assert inputs.sample_size == 3, (
            f"sample_size={inputs.sample_size}; expected 3 (car A sessions only). "
            "Without Fix 2 the query returns sessions for all cars."
        )
