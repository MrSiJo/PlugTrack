"""Unit tests for the Car model (no DB required)."""
from __future__ import annotations

from plugtrack.models.car import Car


def test_display_name_prefers_name_then_make_model():
    c = Car(make="Cupra", model="Born", battery_kwh=58, nominal_efficiency_mi_per_kwh=3.5, user_id=1)
    assert c.display_name == "Cupra Born"
    c.name = "Daily"
    assert c.display_name == "Daily"
