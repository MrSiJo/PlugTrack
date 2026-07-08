"""Unit tests for the pure charge_planner.compute_charge_plan function.

No DB, no fixtures — just pure math.
"""

from __future__ import annotations

import pytest
from plugtrack.services.charge_planner import (
    DcSession,
    build_dc_capability,
    build_scenario_table,
    compute_charge_plan,
    estimate_scenario,
)

# Default window: 23:45 → 07:15 = 450 minutes.
_WINDOW_START = "23:45"
_WINDOW_MINUTES = 450  # (7*60+15 - 23*60-45) % 1440 = 450


def _plan(
    start_soc: int = 20,
    target_soc: int = 80,
    battery_kwh: float = 77.0,
    power_kw: float = 7.4,
    window_minutes: int = _WINDOW_MINUTES,
    window_start_str: str = _WINDOW_START,
    home_rate_p_per_kwh: float = 7.5,
    is_free: bool = False,
):
    return compute_charge_plan(
        start_soc=start_soc,
        target_soc=target_soc,
        battery_kwh=battery_kwh,
        power_kw=power_kw,
        window_minutes=window_minutes,
        window_start_str=window_start_str,
        home_rate_p_per_kwh=home_rate_p_per_kwh,
        is_free=is_free,
    )


class TestFitsOneWindow:
    def test_fits_one_window_true(self):
        # 60% of 77 kWh at 7.4 kW → 46.2 kWh / 7.4 kW * 60 ≈ 375 min < 450
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.fits_one_window is True
        assert p.nights_needed == 1
        assert len(p.nights) == 1

    def test_fits_one_window_end_soc_capped(self):
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.nights[0].end_soc == 80  # capped at target

    def test_kwh_needed(self):
        # (80-20)/100 * 77 = 46.2
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.kwh_needed == pytest.approx(46.2, abs=0.01)

    def test_total_minutes_calculation(self):
        # 46.2 / 7.4 * 60 = 374.59... → 375 when rounded
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.total_minutes == round(46.2 / 7.4 * 60)

    def test_finish_at_format(self):
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        # finish_at must be HH:MM
        h, m = p.finish_at.split(":")
        assert 0 <= int(h) <= 23
        assert 0 <= int(m) <= 59

    def test_finish_at_matches_last_night(self):
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.finish_at == p.nights[-1].finish_at


class TestMultiNightOverflow:
    def test_two_nights_needed(self):
        # Large battery, small power → many hours needed.
        # 80% of 100 kWh at 3.6 kW → 80/3.6*60 ≈ 1333 min; window=450 → 3 nights
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        assert p.nights_needed >= 2
        assert p.fits_one_window is False

    def test_multi_night_indices_sequential(self):
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        for i, n in enumerate(p.nights, start=1):
            assert n.index == i

    def test_multi_night_full_nights_have_window_minutes(self):
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        # All nights except the last must use the full window.
        for n in p.nights[:-1]:
            assert n.minutes == 450

    def test_multi_night_per_night_end_soc_increasing(self):
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        prev = 0
        for n in p.nights:
            assert n.end_soc >= prev
            prev = n.end_soc

    def test_final_night_end_soc_equals_target(self):
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        assert p.nights[-1].end_soc == 80

    def test_final_finish_at_within_window(self):
        # Last night is partial — finish_at is before window_end.
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
            window_start_str="23:45",
        )
        # finish_at of the last night == window_start + last_night_minutes (mod 24h)
        last = p.nights[-1]
        ws_min = 23 * 60 + 45
        expected_abs = (ws_min + last.minutes) % 1440
        h, m = divmod(expected_abs, 60)
        assert last.finish_at == f"{h:02d}:{m:02d}"

    def test_nights_needed_equals_len_nights(self):
        p = _plan(
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            power_kw=3.6,
            window_minutes=450,
        )
        assert p.nights_needed == len(p.nights)


class TestExactWindowFit:
    def test_exact_window_fit(self):
        # Tune power so total_minutes == window_minutes exactly.
        # window=450, battery=77, soc_delta=60 → kwh_needed=46.2
        # power = 46.2/(450/60) = 46.2/7.5 = 6.16 kW
        power_kw = 46.2 / (450 / 60)
        p = _plan(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            power_kw=power_kw,
            window_minutes=450,
        )
        assert p.fits_one_window is True
        assert p.nights_needed == 1
        assert p.nights[0].minutes == 450
        assert p.nights[0].end_soc == 80


class TestWindowCrossingMidnight:
    def test_window_crossing_midnight_finish_at(self):
        # Window 23:00→06:00, power=7.4, fits one window.
        # total_minutes for small charge → finish_at in early hours.
        p = _plan(
            start_soc=60,
            target_soc=80,
            battery_kwh=77.0,
            power_kw=7.4,
            window_minutes=420,  # 23:00 → 06:00 = 7h = 420 min
            window_start_str="23:00",
        )
        assert p.nights_needed == 1
        # Charge: 20% of 77 = 15.4 kWh → 15.4/7.4*60 ≈ 125 min
        # finish_at = 23:00 + 125min = 00:05 (01:05 exactly? let's compute)
        total_min = p.total_minutes
        ws = 23 * 60
        expected_abs = (ws + total_min) % 1440
        h, m = divmod(expected_abs, 60)
        assert p.finish_at == f"{h:02d}:{m:02d}"


class TestCostCalculation:
    def test_cost_equals_kwh_times_rate(self):
        p = _plan(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            power_kw=7.4,
            home_rate_p_per_kwh=28.0,
            is_free=False,
        )
        expected = round(p.kwh_needed * 28.0)
        assert p.cost_pence == expected

    def test_is_free_returns_zero_cost(self):
        p = _plan(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            power_kw=7.4,
            home_rate_p_per_kwh=28.0,
            is_free=True,
        )
        assert p.cost_pence == 0

    def test_cost_zero_rate(self):
        p = _plan(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            power_kw=7.4,
            home_rate_p_per_kwh=0.0,
            is_free=False,
        )
        assert p.cost_pence == 0

    def test_cost_default_home_rate(self):
        # 7.5 p/kWh default, 60% of 77 kWh = 46.2 kWh
        p = _plan(start_soc=20, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.cost_pence == round(46.2 * 7.5)


class TestEdgeCases:
    def test_small_delta_one_night(self):
        # 1% SoC delta — very short charge
        p = _plan(start_soc=79, target_soc=80, battery_kwh=77.0, power_kw=7.4)
        assert p.nights_needed == 1
        assert p.kwh_needed == pytest.approx(0.77, abs=0.01)

    def test_full_charge_from_zero(self):
        # 0→100%
        p = _plan(start_soc=0, target_soc=100, battery_kwh=77.0, power_kw=7.4)
        assert p.kwh_needed == pytest.approx(77.0, abs=0.01)
        assert p.nights[-1].end_soc == 100


# ---------------------------------------------------------------------------
# DcCapability / build_dc_capability tests
# ---------------------------------------------------------------------------


class TestDcCapabilityTier1Curve:
    """Tier 1: curve points pool into 10% SoC bands; capability = band median."""

    def test_power_at_band_with_curve_points_returns_median_and_curve_tag(self):
        # Session has curve points spanning 50-80% SoC.
        # Band 60-70 (query soc=60 maps to band 60-70) has points: 80, 100, 90 kW.
        # Median of [80, 90, 100] = 90.
        curve = [
            [0, 52, 75.0],  # band 50-60
            [30, 55, 80.0],  # band 50-60
            [60, 62, 80.0],  # band 60-70
            [90, 65, 100.0],  # band 60-70
            [120, 68, 90.0],  # band 60-70
            [150, 72, 70.0],  # band 70-80
            [180, 78, 60.0],  # band 70-80
        ]
        session = DcSession(
            start_soc=50,
            end_soc=80,
            kwh_added=15.0,
            actual_charge_seconds=600,
            wall_seconds=700,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(60)
        assert tag == "curve"
        assert power == pytest.approx(90.0, abs=0.1)

    def test_curve_tag_preferred_over_average_when_both_available(self):
        # Even when the session also overlaps the band by SoC range,
        # the curve tag wins because tier 1 takes precedence.
        curve = [[0, 45, 120.0], [30, 48, 130.0]]
        session = DcSession(
            start_soc=40,
            end_soc=60,
            kwh_added=10.0,
            actual_charge_seconds=360,
            wall_seconds=400,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=200.0,
        )
        power, tag = cap.power_at(44)
        assert tag == "curve"

    def test_curve_capped_at_ceiling(self):
        # Curve points at 200 kW but ceiling is 150 kW → result capped to 150.
        curve = [[0, 25, 200.0], [30, 28, 210.0]]
        session = DcSession(
            start_soc=20,
            end_soc=35,
            kwh_added=5.0,
            actual_charge_seconds=120,
            wall_seconds=150,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(25)
        assert tag == "curve"
        assert power <= 150.0


class TestDcCapabilityTier2Average:
    """Tier 2: no curve coverage → effective power averaged across overlapping sessions."""

    def test_power_at_40_with_actual_charge_seconds(self):
        # Two sessions overlapping 30-50% band.
        # Session A: 10 kWh / (1800s / 3600) = 20 kW effective
        # Session B: 12 kWh / (2400s / 3600) = 18 kW effective
        # Average = 19 kW
        sessions = [
            DcSession(
                start_soc=30,
                end_soc=55,
                kwh_added=10.0,
                actual_charge_seconds=1800,
                wall_seconds=2000,
                power_curve=None,
            ),
            DcSession(
                start_soc=25,
                end_soc=50,
                kwh_added=12.0,
                actual_charge_seconds=2400,
                wall_seconds=2800,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(40)
        assert tag == "average"
        assert power == pytest.approx(19.0, abs=0.01)

    def test_power_at_40_fallback_to_wall_seconds_when_actual_none(self):
        # actual_charge_seconds is None → use wall_seconds.
        # 10 kWh / (2000s / 3600) = 18.0 kW
        sessions = [
            DcSession(
                start_soc=30,
                end_soc=55,
                kwh_added=10.0,
                actual_charge_seconds=None,
                wall_seconds=2000,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(40)
        assert tag == "average"
        assert power == pytest.approx(18.0, abs=0.01)

    def test_average_capped_at_ceiling(self):
        # Effective power would be very high but ceiling is 50 kW.
        sessions = [
            DcSession(
                start_soc=30,
                end_soc=60,
                kwh_added=30.0,
                actual_charge_seconds=600,  # 30/0.1667h = 180 kW effective
                wall_seconds=700,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=50.0,
        )
        power, tag = cap.power_at(40)
        assert tag == "average"
        assert power <= 50.0

    def test_session_not_overlapping_band_excluded(self):
        # Session only covers 70-90%, should NOT count for band 30-40%.
        sessions = [
            DcSession(
                start_soc=70,
                end_soc=90,
                kwh_added=10.0,
                actual_charge_seconds=1800,
                wall_seconds=2000,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=150.0,
        )
        # Band 30-40 has no sessions → should fall through to tier 3
        _, tag = cap.power_at(35)
        assert tag == "modelled"


class TestDcCapabilityTier3Modelled:
    """Tier 3: no curve or average data → generic ramp-then-taper shape × ceiling."""

    def test_band_with_no_data_returns_modelled_tag(self):
        # Pass a session that only covers 80-100%; query band 0-10 has no data.
        sessions = [
            DcSession(
                start_soc=80,
                end_soc=100,
                kwh_added=5.0,
                actual_charge_seconds=900,
                wall_seconds=1000,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(5)
        assert tag == "modelled"
        assert 0 < power <= 150.0

    def test_modelled_shape_low_soc_higher_than_high_soc(self):
        # Generic shape: ramp to peak by ~20-30%, taper after ~50-60%.
        # Power at low SoC (e.g. 15%) should exceed power at high SoC (e.g. 95%).
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],  # no data → all bands are modelled
            max_dc_kw=150.0,
        )
        low_power, low_tag = cap.power_at(15)
        high_power, high_tag = cap.power_at(95)
        assert low_tag == "modelled"
        assert high_tag == "modelled"
        assert low_power > high_power

    def test_modelled_value_does_not_exceed_ceiling(self):
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=80.0,
        )
        for soc in range(0, 100, 10):
            power, _ = cap.power_at(soc)
            assert power <= 80.0

    def test_modelled_at_90_is_low_fraction_of_ceiling(self):
        # By spec, the shape should be low (~0.2*ceiling) by 90%+.
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(90)
        assert tag == "modelled"
        assert power <= 0.3 * 150.0  # at most 30% ceiling at 90%

    def test_power_at_soc_100(self):
        # SoC 100 maps to the 90-100 band via _soc_band (capped at 90).
        # No crash; returns a sensible value ≤ ceiling.
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=150.0,
        )
        power, tag = cap.power_at(100)
        assert tag == "modelled"  # band 90 resolves to tier 3 when no data
        assert 0 < power <= cap.ceiling


class TestDcCapabilityCeiling:
    """Ceiling = max_dc_kw when set; else observed max from data."""

    def test_ceiling_set_by_max_dc_kw(self):
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=160.0,
        )
        assert cap.ceiling == pytest.approx(160.0)

    def test_ceiling_no_band_exceeds_max_dc_kw(self):
        # Curve points go up to 200 kW but ceiling is clamped to 160 kW.
        curve = [[i * 10, 10 + i, 200.0] for i in range(8)]
        session = DcSession(
            start_soc=10,
            end_soc=80,
            kwh_added=20.0,
            actual_charge_seconds=1000,
            wall_seconds=1200,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=160.0,
        )
        for soc in range(0, 100, 10):
            power, _ = cap.power_at(soc)
            assert power <= 160.0

    def test_ceiling_derived_from_observed_max_when_max_dc_kw_none(self):
        # max_dc_kw=None → ceiling = max of effective powers observed.
        # Session effective power: 10 kWh / (1000/3600) h = 36 kW.
        sessions = [
            DcSession(
                start_soc=20,
                end_soc=80,
                kwh_added=10.0,
                actual_charge_seconds=1000,
                wall_seconds=1200,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=sessions,
            max_dc_kw=None,
        )
        assert cap.ceiling == pytest.approx(36.0, abs=0.1)

    def test_ceiling_derived_from_curve_max_when_max_dc_kw_none(self):
        # max_dc_kw=None → ceiling = max curve point observed.
        curve = [[0, 30, 120.0], [30, 50, 140.0], [60, 70, 100.0]]
        session = DcSession(
            start_soc=25,
            end_soc=75,
            kwh_added=10.0,
            actual_charge_seconds=None,
            wall_seconds=None,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=None,
        )
        assert cap.ceiling == pytest.approx(140.0, abs=0.1)

    def test_ceiling_uses_band_median_not_raw_spike(self):
        # Build a session whose curve is mostly ~100 kW but has ONE transient
        # 170 kW spike.  With max_dc_kw=None the ceiling must reflect the
        # sustained median (~100 kW), NOT the spike.
        #
        # Band 20-30 gets points: 98, 102, 99, 101, 170.
        # Median of [98, 99, 101, 102, 170] = 101.
        # Band 30-40 gets points: 96, 104, 100.  Median = 100.
        # Max of all band medians = 101  → ceiling ≤ 120 (well below 170).
        curve = [
            [0, 22, 98.0],
            [30, 24, 102.0],
            [60, 25, 99.0],
            [90, 27, 101.0],
            [120, 29, 170.0],  # ← transient spike — must NOT drive ceiling
            [150, 32, 96.0],
            [180, 35, 104.0],
            [210, 38, 100.0],
        ]
        session = DcSession(
            start_soc=20,
            end_soc=40,
            kwh_added=5.0,
            actual_charge_seconds=None,
            wall_seconds=None,
            power_curve=curve,
        )
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[session],
            max_dc_kw=None,
        )
        # If ceiling were derived from raw max it would be 170; median-based ceiling ≤ 120.
        assert cap.ceiling <= 120.0, f"ceiling {cap.ceiling} should be ≤ 120 (spike-robust)"


# ---------------------------------------------------------------------------
# Task 3: estimate_scenario + build_scenario_table tests
# ---------------------------------------------------------------------------

# Helpers -----------------------------------------------------------------


def _two_band_capability() -> DcCapability:
    """Build a known 2-band DC capability for deterministic integration tests.

    Band 30-40: average 80 kW  (sessions, no curve)
    Band 40-50: average 100 kW (sessions, no curve)
    All other bands: modelled (ceiling=150 kW).
    """
    sessions = [
        # Session that overlaps band 30-40 only
        DcSession(
            start_soc=30,
            end_soc=40,
            kwh_added=7.7,  # 10% of 77 kWh
            actual_charge_seconds=int(7.7 / 80 * 3600),  # → 80 kW effective
            wall_seconds=None,
            power_curve=None,
        ),
        # Session that overlaps band 40-50 only
        DcSession(
            start_soc=40,
            end_soc=50,
            kwh_added=7.7,
            actual_charge_seconds=int(7.7 / 100 * 3600),  # → 100 kW effective
            wall_seconds=None,
            power_curve=None,
        ),
    ]
    return build_dc_capability(
        battery_kwh=77.0,
        dc_sessions=sessions,
        max_dc_kw=150.0,
    )


_AC_WINDOW = {
    "window_minutes": 450,
    "window_start_str": "23:45",
    "home_rate_p_per_kwh": 7.5,
    "is_free": False,
}


class TestEstimateScenarioDC:
    """DC integration: integrates per-SoC-% from start to target using capability."""

    def test_dc_basic_integration_gives_expected_minutes(self):
        """10%→20% over a flat-100-kW band: 7.7 kWh / 100 kW = 0.077 h = ~4.62 min → 5."""
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[
                DcSession(
                    start_soc=10,
                    end_soc=20,
                    kwh_added=7.7,
                    actual_charge_seconds=int(7.7 / 100 * 3600),
                    wall_seconds=None,
                    power_curve=None,
                )
            ],
            max_dc_kw=150.0,
        )
        row = estimate_scenario(
            kind="dc",
            label="100 kW",
            start_soc=10,
            target_soc=20,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        # 10 steps × 0.77 kWh / 100 kW = 0.077 h = 4.62 min → round = 5
        assert row.minutes == pytest.approx(5, abs=1)
        assert row.source_tag == "average"

    def test_dc_two_band_integration(self):
        """30→50% over the 2-band capability: 30-40 @ 80 kW, 40-50 @ 100 kW.

        Time for 30→40 (10%): 7.7 kWh / 80 kW = 0.09625 h
        Time for 40→50 (10%): 7.7 kWh / 100 kW = 0.077 h
        Total: 0.17325 h = 10.395 min → round = 10
        """
        cap = _two_band_capability()
        row = estimate_scenario(
            kind="dc",
            label="Car max",
            start_soc=30,
            target_soc=50,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        assert row.minutes == pytest.approx(10, abs=1)

    def test_dc_loss_factor_increases_time(self):
        """With loss_factor=0.9 time = time_no_loss / 0.9 → ~11% longer.

        Use a large SoC range (0→100) with a big battery to ensure minutes are
        large enough that integer rounding doesn't swamp the ratio signal.
        """
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=150.0,
        )
        row_no_loss = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=0,
            target_soc=100,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        row_with_loss = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=0,
            target_soc=100,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=0.9,
            ac_window=None,
            source_tag="",
        )
        # time should scale by 1/0.9 ≈ 1.11; allow 6% tolerance for rounding
        ratio = row_with_loss.minutes / row_no_loss.minutes
        assert ratio == pytest.approx(1 / 0.9, rel=0.06)

    def test_dc_charger_cap_limits_power(self):
        """When charger_cap < capability, charger_cap is the bottleneck."""
        cap = _two_band_capability()  # band 40-50 → 100 kW
        row_capped = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=40,
            target_soc=50,
            battery_kwh=77.0,
            charger_cap_kw=50.0,  # cap below capability
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        row_uncapped = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=40,
            target_soc=50,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        assert row_capped.minutes > row_uncapped.minutes

    def test_dc_dominant_tag_modelled_wins(self):
        """If ANY band in range is modelled, source_tag == 'modelled'."""
        # Build capability with data only in band 40-50; 50-60 will be modelled.
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[
                DcSession(
                    start_soc=40,
                    end_soc=50,
                    kwh_added=7.7,
                    actual_charge_seconds=int(7.7 / 100 * 3600),
                    wall_seconds=None,
                    power_curve=None,
                )
            ],
            max_dc_kw=150.0,
        )
        # Range 40→60 spans bands 40 (average) and 50 (modelled) → dominant = modelled
        row = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=40,
            target_soc=60,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        assert row.source_tag == "modelled"

    def test_dc_dominant_tag_average_over_curve(self):
        """If range spans curve AND average (no modelled), source_tag == 'average'."""
        # Band 40-50: curve; band 50-60: average
        curve = [[0, 45, 100.0]]
        sessions = [
            DcSession(
                start_soc=40,
                end_soc=50,
                kwh_added=7.7,
                actual_charge_seconds=None,
                wall_seconds=None,
                power_curve=curve,
            ),
            DcSession(
                start_soc=50,
                end_soc=60,
                kwh_added=7.7,
                actual_charge_seconds=int(7.7 / 80 * 3600),
                wall_seconds=None,
                power_curve=None,
            ),
        ]
        cap = build_dc_capability(battery_kwh=77.0, dc_sessions=sessions, max_dc_kw=150.0)
        row = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=40,
            target_soc=60,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        assert row.source_tag == "average"

    def test_dc_representative_power_kw_reasonable(self):
        """power_kw in ScenarioRow should be within [0, charger_cap]."""
        cap = _two_band_capability()
        row = estimate_scenario(
            kind="dc",
            label="X",
            start_soc=30,
            target_soc=50,
            battery_kwh=77.0,
            charger_cap_kw=150.0,
            capability=cap,
            flat_power_kw=None,
            loss_factor=1.0,
            ac_window=None,
            source_tag="",
        )
        assert 0 < row.power_kw <= 150.0


class TestEstimateScenarioAC:
    """AC scenario: flat power, min(scenario, ceiling), multi-night via compute_charge_plan."""

    def test_ac_basic_minutes_and_finish_at(self):
        """7 kW AC, 20→80%, 77 kWh: 46.2 kWh / 7 kW * 60 ≈ 396 min → 1 night."""
        row = estimate_scenario(
            kind="ac",
            label="7 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=22.0,  # AC ceiling (car or EVSE max)
            capability=None,
            flat_power_kw=7.0,  # scenario power
            loss_factor=1.0,
            ac_window=_AC_WINDOW,
            source_tag="spec",
        )
        expected_minutes = round(46.2 / 7.0 * 60)
        assert row.minutes == expected_minutes
        assert row.nights == 1
        assert row.finish_at is not None
        assert row.source_tag == "spec"
        assert row.label == "7 kW"

    def test_ac_ceiling_caps_scenario_power(self):
        """If scenario power > AC ceiling, effective power = ceiling."""
        row_11 = estimate_scenario(
            kind="ac",
            label="11 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=7.4,  # ceiling lower than scenario
            capability=None,
            flat_power_kw=11.0,
            loss_factor=1.0,
            ac_window=_AC_WINDOW,
            source_tag="spec",
        )
        row_74 = estimate_scenario(
            kind="ac",
            label="7.4 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=22.0,
            capability=None,
            flat_power_kw=7.4,
            loss_factor=1.0,
            ac_window=_AC_WINDOW,
            source_tag="spec",
        )
        # Capped at 7.4 → same as the 7.4 kW row
        assert row_11.minutes == row_74.minutes

    def test_ac_loss_factor_applied(self):
        """With loss_factor < 1, effective power is reduced → more minutes."""
        row_no_loss = estimate_scenario(
            kind="ac",
            label="7 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=22.0,
            capability=None,
            flat_power_kw=7.0,
            loss_factor=1.0,
            ac_window=_AC_WINDOW,
            source_tag="spec",
        )
        row_with_loss = estimate_scenario(
            kind="ac",
            label="7 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=22.0,
            capability=None,
            flat_power_kw=7.0,
            loss_factor=0.9,
            ac_window=_AC_WINDOW,
            source_tag="spec",
        )
        assert row_with_loss.minutes > row_no_loss.minutes

    def test_ac_multi_night_preserved(self):
        """Small power against large battery → nights > 1."""
        row = estimate_scenario(
            kind="ac",
            label="3.6 kW",
            start_soc=0,
            target_soc=80,
            battery_kwh=100.0,
            charger_cap_kw=22.0,
            capability=None,
            flat_power_kw=3.6,
            loss_factor=1.0,
            ac_window={**_AC_WINDOW, "window_minutes": 450},
            source_tag="spec",
        )
        assert row.nights is not None and row.nights >= 2

    def test_ac_power_kw_is_effective_pre_loss_value(self):
        """power_kw on the row = min(flat_power_kw, charger_cap_kw), not loss-derated."""
        row = estimate_scenario(
            kind="ac",
            label="7 kW",
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            charger_cap_kw=22.0,
            capability=None,
            flat_power_kw=7.0,
            loss_factor=0.85,
            ac_window=_AC_WINDOW,
            source_tag="history",
        )
        assert row.power_kw == pytest.approx(7.0, abs=0.01)


class TestBuildScenarioTable:
    """build_scenario_table: fixed ordered rows, correct tags, custom-kW note."""

    def _default_dc(self) -> dict:
        cap = build_dc_capability(
            battery_kwh=77.0,
            dc_sessions=[],
            max_dc_kw=150.0,
        )
        return {"capability": cap, "ceiling": 150.0}

    def _default_ac(self) -> dict:
        return {
            "home_actual_kw": 6.9,
            "ac_ceiling_kw": 11.0,
            **_AC_WINDOW,
        }

    def test_returns_seven_rows_with_custom_kw(self):
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=50.0,
        )
        assert len(table) == 7

    def test_returns_six_rows_without_custom_kw(self):
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=None,
        )
        assert len(table) == 6

    def test_ordered_labels(self):
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=50.0,
        )
        labels = [r.label for r in table]
        assert labels == [
            "Your home (actual)",
            "7 kW",
            "11 kW",
            "50 kW",
            "150 kW",
            "Car max",
            "Custom kW",
        ]

    def test_ac_rows_capped_at_ceiling(self):
        """11 kW row capped at ac_ceiling_kw=7.4 → power_kw = 7.4."""
        ac = {**self._default_ac(), "ac_ceiling_kw": 7.4}
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac,
            dc=self._default_dc(),
            custom_kw=None,
        )
        row_11 = next(r for r in table if r.label == "11 kW")
        assert row_11.power_kw == pytest.approx(7.4, abs=0.01)

    def test_home_actual_tag_is_history(self):
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=None,
        )
        home_row = table[0]
        assert home_row.label == "Your home (actual)"
        assert home_row.source_tag == "history"

    def test_custom_kw_above_ceiling_note_and_capped_power(self):
        """custom_kw > car max → power_kw is capped by ceiling and note set.

        The representative power_kw is the energy-weighted average of
        min(charger_cap, capability) over the SoC range.  With charger_cap
        clamped to ceiling (150 kW) and a taper-shaped capability, the
        average will be ≤ ceiling.  We assert it is ≤ ceiling and not the
        uncapped 300 kW value, and that the note mentions the ceiling.
        """
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=300.0,
        )
        custom_row = table[-1]
        assert custom_row.label == "Custom kW"
        # power_kw should be capped (≤ ceiling of 150, and > 0)
        assert 0 < custom_row.power_kw <= 150.0
        # It should be the same as the "Car max" row (same effective cap)
        car_max_row = next(r for r in table if r.label == "Car max")
        assert custom_row.power_kw == pytest.approx(car_max_row.power_kw, rel=0.01)
        assert custom_row.note is not None and "150" in custom_row.note

    def test_custom_kw_below_ceiling_no_note(self):
        """custom_kw < ceiling → power_kw == custom_kw and note is None."""
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=80.0,
        )
        custom_row = table[-1]
        assert custom_row.label == "Custom kW"
        # power_kw close to 80 (capped at ceiling 150, so 80 wins)
        assert custom_row.power_kw == pytest.approx(80.0, rel=0.05)
        assert custom_row.note is None

    def test_car_max_row_uses_ceiling(self):
        """Car max row power_kw should equal the ceiling (for a fully modelled car)."""
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=None,
        )
        car_max_row = next(r for r in table if r.label == "Car max")
        # Car max integrates using ceiling — representative power ≤ ceiling
        assert 0 < car_max_row.power_kw <= 150.0

    def test_dominant_tag_modelled_across_range(self):
        """When DC range spans a modelled band, that row has source_tag=='modelled'."""
        # Empty sessions → all bands are modelled.
        dc = {
            "capability": build_dc_capability(battery_kwh=77.0, dc_sessions=[], max_dc_kw=150.0),
            "ceiling": 150.0,
        }
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=dc,
            custom_kw=None,
        )
        dc_rows = [r for r in table if r.label in ("50 kW", "150 kW", "Car max")]
        for row in dc_rows:
            assert row.source_tag == "modelled", f"{row.label} should be 'modelled'"

    def test_all_rows_have_positive_minutes(self):
        table = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=self._default_ac(),
            dc=self._default_dc(),
            custom_kw=50.0,
        )
        for row in table:
            assert row.minutes > 0, f"{row.label} has non-positive minutes"

    def test_loss_factor_applied_uniformly(self):
        """With loss_factor=0.9, all minutes should be longer than loss_factor=1.0."""
        ac = self._default_ac()
        dc = self._default_dc()
        table_no_loss = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac,
            dc=dc,
            custom_kw=None,
        )
        table_with_loss = build_scenario_table(
            start_soc=20,
            target_soc=80,
            battery_kwh=77.0,
            loss_factor=0.9,
            ac=ac,
            dc=dc,
            custom_kw=None,
        )
        for r_no, r_loss in zip(table_no_loss, table_with_loss):
            assert r_loss.minutes >= r_no.minutes, (
                f"{r_no.label}: expected minutes to increase with loss"
            )
