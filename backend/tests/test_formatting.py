"""Tests for backend distance formatting helpers."""
from __future__ import annotations

import pytest

from plugtrack.services.formatting import format_distance, km_to_mi, mi_to_km


def test_km_to_mi_zero():
    assert km_to_mi(0.0) == 0.0


def test_km_to_mi_one_mile_round_trip():
    assert km_to_mi(1.609344) == pytest.approx(1.0)
    assert mi_to_km(1.0) == pytest.approx(1.609344)


def test_format_distance_km_passthrough():
    assert format_distance(100.0, "km") == "100 km"
    assert format_distance(0.0, "km") == "0 km"


def test_format_distance_mi_converts():
    assert format_distance(100.0, "mi") == "62 mi"
    assert format_distance(160.9344, "mi") == "100 mi"


def test_format_distance_large_values():
    assert format_distance(100_000.0, "km") == "100000 km"
    assert format_distance(100_000.0, "mi") == "62137 mi"


def test_format_distance_rounds_floats():
    assert format_distance(1.4, "km") == "1 km"
    assert format_distance(1.6, "km") == "2 km"


def test_km_mi_round_trip():
    for km in (0.5, 25.0, 1000.0):
        assert mi_to_km(km_to_mi(km)) == pytest.approx(km, rel=1e-9)
