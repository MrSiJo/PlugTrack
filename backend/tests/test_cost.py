"""Exhaustive tests for the cost-precedence rule (spec §3.3 lines 143–162)."""
from __future__ import annotations

import pytest

from plugtrack.models.location import Location
from plugtrack.services.cost import compute_session_cost


HOME_RATE = 7.5  # p/kWh — the seeded catalogue default


def _loc(**kwargs) -> Location:
    """Build a Location instance without persisting it (for cost tests only)."""
    defaults = dict(
        user_id=1,
        name=None,
        centroid_lat=50.0,
        centroid_lng=0.0,
        radius_m=100,
        is_home=False,
        is_free=False,
        default_cost_per_kwh_p=None,
    )
    defaults.update(kwargs)
    return Location(**defaults)


def test_total_override_wins_over_everything():
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=21.5,
        location=_loc(is_free=True, default_cost_per_kwh_p=15.0),
        session_overrides={"total_cost_pence_override": 1840},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 1840
    assert cost_basis == "override_total"
    # No per-kwh override given — tariff is None.
    assert tariff is None


def test_per_kwh_override_no_total_uses_kwh_times_override():
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=20.0,
        location=_loc(is_free=True, default_cost_per_kwh_p=15.0),
        session_overrides={"cost_per_kwh_override_p": 79.0},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 1580  # round(20 * 79)
    assert cost_basis == "override_per_kwh"
    assert tariff == 79.0


def test_location_free_zeroes_cost():
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=42.5,
        location=_loc(is_free=True, default_cost_per_kwh_p=15.0),
        session_overrides={},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 0
    assert cost_basis == "location_free"
    assert tariff == 0.0


def test_location_rate_overrides_global_home_rate():
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=10.0,
        location=_loc(default_cost_per_kwh_p=12.5),
        session_overrides={},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 125
    assert cost_basis == "location_rate"
    assert tariff == 12.5


def test_home_rate_when_nothing_else_set():
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=10.0,
        location=None,
        session_overrides={},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 75  # round(10 * 7.5)
    assert cost_basis == "home_rate"
    assert tariff == HOME_RATE


def test_home_rate_when_location_unlabelled():
    """Unlabelled location (no flags, no default rate) → home rate fallback."""
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=10.0,
        location=_loc(),  # unlabelled — all defaults
        session_overrides={},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 75
    assert cost_basis == "home_rate"
    assert tariff == HOME_RATE


def test_mixed_override_total_wins_per_kwh_preserved_as_tariff():
    """Critical edge case: both overrides set.

    `total_override = 1840`, `per_kwh_override = 79`, `kwh = 21.5`:
    - `cost_pence = 1840` (override_total wins)
    - `cost_basis = 'override_total'`
    - `tariff_p_per_kwh = 79.0` (preserved for breakdown display so
      the UI can show "21.5 × 79p = £16.99 + £1.41 fees = £18.40").
    """
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=21.5,
        location=None,
        session_overrides={
            "total_cost_pence_override": 1840,
            "cost_per_kwh_override_p": 79.0,
        },
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 1840
    assert cost_basis == "override_total"
    assert tariff == 79.0


def test_total_override_zero_does_not_fall_through():
    """`total_override == 0` must be honoured (free public charger)."""
    cost_pence, cost_basis, _ = compute_session_cost(
        kwh_added=10.0,
        location=None,
        session_overrides={"total_cost_pence_override": 0},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 0
    assert cost_basis == "override_total"


def test_per_kwh_override_zero_does_not_fall_through():
    """`per_kwh_override == 0` must be honoured (zero-rate tariff)."""
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=10.0,
        location=None,
        session_overrides={"cost_per_kwh_override_p": 0.0},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 0
    assert cost_basis == "override_per_kwh"
    assert tariff == 0.0


def test_location_default_zero_uses_zero_not_home_rate():
    """`location.default_cost_per_kwh_p == 0.0` must be honoured."""
    cost_pence, cost_basis, tariff = compute_session_cost(
        kwh_added=10.0,
        location=_loc(default_cost_per_kwh_p=0.0),
        session_overrides={},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    assert cost_pence == 0
    assert cost_basis == "location_rate"
    assert tariff == 0.0


def test_round_to_integer_pence():
    """Cost pence must be a round-half-to-even integer."""
    cost_pence, _, _ = compute_session_cost(
        kwh_added=21.5,
        location=None,
        session_overrides={"cost_per_kwh_override_p": 12.345},
        settings_default_home_rate_p_per_kwh=HOME_RATE,
    )
    # 21.5 * 12.345 = 265.4175 → round to 265
    assert cost_pence == 265
    assert isinstance(cost_pence, int)
