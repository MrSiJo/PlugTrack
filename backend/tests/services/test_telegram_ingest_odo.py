# backend/tests/services/test_telegram_ingest_odo.py
"""Tests for odometer mapping in _extraction_to_edit_kwargs (telegram_ingest.py)."""
from __future__ import annotations


def test_extraction_to_edit_kwargs_maps_odometer():
    from plugtrack.services.telegram_ingest import _extraction_to_edit_kwargs
    from plugtrack.services.screenshot_extraction import Extraction

    e = Extraction(
        source="osprey", has_cost=True, energy_kwh=9.78, cost_total_pence=851,
        cost_per_kwh_pence=87.0, start_at="2026-06-12T14:25:00",
        end_at="2026-06-12T14:40:00", soc_start=56, soc_end=70,
        location_name=None, location_address=None, network=None,
        peak_kw=40.0, confidence=0.95,
        odometer=11056.0, odometer_unit="mi",
    )
    kwargs = _extraction_to_edit_kwargs(e)
    assert kwargs["odometer"] == 11056.0
    assert kwargs["odometer_unit"] == "mi"


def test_extraction_to_edit_kwargs_no_odometer_omits_field():
    from plugtrack.services.telegram_ingest import _extraction_to_edit_kwargs
    from plugtrack.services.screenshot_extraction import Extraction

    e = Extraction(
        source="osprey", has_cost=True, energy_kwh=9.78, cost_total_pence=851,
        cost_per_kwh_pence=87.0, start_at="2026-06-12T14:25:00",
        end_at="2026-06-12T14:40:00", soc_start=56, soc_end=70,
        location_name=None, location_address=None, network=None,
        peak_kw=40.0, confidence=0.95,
        odometer=None, odometer_unit=None,
    )
    kwargs = _extraction_to_edit_kwargs(e)
    assert "odometer" not in kwargs
    assert "odometer_unit" not in kwargs
