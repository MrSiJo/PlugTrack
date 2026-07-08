"""Unit tests for the pure charge_planner.build_blended_plan function.

No DB, no fixtures — composes estimate_scenario (DC) + compute_charge_plan (home).
"""

from __future__ import annotations

import pytest
from plugtrack.services.charge_planner import (
    build_blended_plan,
    build_dc_capability,
)

_WINDOW = {"window_minutes": 450, "window_start_str": "23:45"}


def _capability(ceiling: float = 150.0):
    # Empty history → pure "modelled" tier, fully deterministic, capped at ceiling.
    return build_dc_capability(battery_kwh=77.0, dc_sessions=[], max_dc_kw=ceiling)


def _blended(
    *,
    start_soc: int = 20,
    dc_stop_soc: int = 60,
    target_soc: int = 80,
    battery_kwh: float = 77.0,
    dc_rate_p: float = 50.0,
    dc_charger_cap_kw: float = 150.0,
    home_power_kw: float = 7.4,
    home_rate_p: float = 7.5,
    is_free: bool = False,
    loss_factor: float = 0.90,
    mi_per_kwh: float | None = 3.6,
):
    return build_blended_plan(
        start_soc=start_soc,
        dc_stop_soc=dc_stop_soc,
        target_soc=target_soc,
        battery_kwh=battery_kwh,
        dc_capability=_capability(dc_charger_cap_kw),
        dc_rate_p=dc_rate_p,
        dc_charger_cap_kw=dc_charger_cap_kw,
        home_power_kw=home_power_kw,
        home_window=_WINDOW,
        home_rate_p=home_rate_p,
        is_free=is_free,
        loss_factor=loss_factor,
        mi_per_kwh=mi_per_kwh,
    )


class TestPhaseEnergy:
    def test_dc_phase_kwh(self):
        # 77 * (60-20)/100 = 30.8
        p = _blended()
        assert p.dc_phase.kwh == pytest.approx(30.8, abs=0.01)

    def test_home_phase_kwh(self):
        # 77 * (80-60)/100 = 15.4
        p = _blended()
        assert p.home_phase.kwh == pytest.approx(15.4, abs=0.01)

    def test_total_kwh_is_sum(self):
        p = _blended()
        assert p.total.kwh == pytest.approx(p.dc_phase.kwh + p.home_phase.kwh, abs=0.01)
        assert p.total.kwh == pytest.approx(46.2, abs=0.01)


class TestPhaseCost:
    def test_dc_cost_uses_dc_rate(self):
        # 30.8 kWh * 50p = 1540p
        p = _blended(dc_rate_p=50.0)
        assert p.dc_phase.cost_pence == 1540

    def test_home_cost_uses_home_rate(self):
        # 15.4 kWh * 7.5p = 115.5 → 116
        p = _blended(home_rate_p=7.5)
        assert p.home_phase.cost_pence == 116

    def test_total_cost_is_sum(self):
        p = _blended()
        assert p.total.cost_pence == p.dc_phase.cost_pence + p.home_phase.cost_pence

    def test_home_free_is_zero_cost(self):
        p = _blended(is_free=True)
        assert p.home_phase.cost_pence == 0


class TestTime:
    def test_total_minutes_is_sum_of_phases(self):
        p = _blended()
        assert p.total.minutes == p.dc_phase.minutes + p.home_phase.minutes

    def test_lower_loss_factor_increases_time(self):
        fast = _blended(loss_factor=1.0)
        slow = _blended(loss_factor=0.5)
        assert slow.dc_phase.minutes > fast.dc_phase.minutes
        assert slow.home_phase.minutes > fast.home_phase.minutes


class TestCostPerMile:
    def test_cost_per_mile(self):
        # cost 1656p over 46.2 kWh * 3.6 mi/kWh = 166.32 mi → 1656/166.32 = 9.957p
        p = _blended()
        assert p.total.cost_per_mile_p == pytest.approx(1656 / (46.2 * 3.6), abs=0.05)

    def test_cost_per_mile_none_when_no_efficiency(self):
        assert _blended(mi_per_kwh=None).total.cost_per_mile_p is None
        assert _blended(mi_per_kwh=0).total.cost_per_mile_p is None

    def test_mi_per_kwh_passthrough(self):
        assert _blended(mi_per_kwh=3.6).total.mi_per_kwh == pytest.approx(3.6)


class TestEdgeCases:
    def test_dc_stop_equals_target_is_pure_dc(self):
        p = _blended(dc_stop_soc=80, target_soc=80)
        assert p.home_phase.kwh == pytest.approx(0.0, abs=0.001)
        assert p.home_phase.minutes == 0
        assert p.home_phase.cost_pence == 0
        assert p.total.kwh == pytest.approx(p.dc_phase.kwh, abs=0.01)

    def test_dc_stop_equals_start_is_pure_home(self):
        p = _blended(start_soc=20, dc_stop_soc=20, target_soc=80)
        assert p.dc_phase.kwh == pytest.approx(0.0, abs=0.001)
        assert p.dc_phase.minutes == 0
        assert p.dc_phase.cost_pence == 0
        assert p.total.kwh == pytest.approx(p.home_phase.kwh, abs=0.01)

    def test_invalid_order_start_above_stop_raises(self):
        with pytest.raises(ValueError):
            _blended(start_soc=60, dc_stop_soc=40, target_soc=80)

    def test_invalid_order_stop_above_target_raises(self):
        with pytest.raises(ValueError):
            _blended(start_soc=20, dc_stop_soc=90, target_soc=80)
