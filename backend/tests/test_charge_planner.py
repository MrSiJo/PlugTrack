"""Unit tests for the pure charge_planner.compute_charge_plan function.

No DB, no fixtures — just pure math.
"""
from __future__ import annotations

import pytest

from plugtrack.services.charge_planner import compute_charge_plan


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
            window_minutes=420,   # 23:00 → 06:00 = 7h = 420 min
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
