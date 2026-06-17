# backend/tests/services/test_screenshot_correlation.py
import json
from pathlib import Path

from plugtrack.services.screenshot_extraction import parse_extraction
from plugtrack.services.screenshot_correlation import correlate

FX = Path(__file__).parent.parent / "fixtures" / "screenshots"


def _load(name: str):
    return parse_extraction(json.loads((FX / name).read_text()))


def test_four_screenshots_merge_into_two_sessions():
    extractions = [
        _load("mycupra_1240.json"),
        _load("osprey.json"),
        _load("tesla.json"),
        _load("mycupra_0842.json"),
    ]
    merged = correlate(extractions)
    assert len(merged) == 2

    by_day = {m.start_at.date().isoformat(): m for m in merged}
    a = by_day["2026-06-12"]
    assert a.energy_kwh == 9.78               # from Osprey
    assert a.cost_total_pence == 851          # from Osprey
    assert a.soc_start == 56 and a.soc_end == 70   # from MyCupra
    assert a.network == "Osprey"
    assert "Land's End" in a.location_name
    assert {"osprey", "mycupra"} <= set(a.source_kinds)

    b = by_day["2026-06-13"]
    assert b.energy_kwh == 37.9124            # from Tesla
    assert b.cost_total_pence == 1706
    assert b.soc_start == 38 and b.soc_end == 100  # from MyCupra
    assert b.network == "Tesla Supercharger"


def test_unrelated_singleton_not_absorbed():
    # Osprey alone on a different day stays its own session.
    osprey = _load("osprey.json")
    tesla = _load("tesla.json")
    merged = correlate([osprey, tesla])
    assert len(merged) == 2


def test_merge_carries_odometer():
    from plugtrack.services.screenshot_extraction import Extraction
    from plugtrack.services.screenshot_correlation import correlate_batch
    e = Extraction(
        source="text", has_cost=False, energy_kwh=9.3, cost_total_pence=None,
        cost_per_kwh_pence=None, start_at="2026-06-15T19:27:00+00:00",
        end_at="2026-06-16T06:59:00+00:00", soc_start=None, soc_end=None,
        location_name="home", location_address=None, network=None, peak_kw=None,
        confidence=0.9, odometer=12345, odometer_unit="mi",
    )
    sessions, _ = correlate_batch([e])
    assert len(sessions) == 1
    assert sessions[0].odometer == 12345
    assert sessions[0].odometer_unit == "mi"


def test_merge_carries_location_short_name():
    from plugtrack.services.screenshot_extraction import Extraction
    from plugtrack.services.screenshot_correlation import correlate_batch
    e = Extraction(
        source="osprey", has_cost=True, energy_kwh=9.78, cost_total_pence=851,
        cost_per_kwh_pence=None, start_at="2026-06-12T10:00:00+00:00",
        end_at="2026-06-12T10:30:00+00:00", soc_start=None, soc_end=None,
        location_name="Land's End Car Park, Penzance", location_address="Land's End, TR19 7AA",
        network="Osprey", peak_kw=None, confidence=0.9,
        location_short_name="Osprey Land's End",
    )
    sessions, _ = correlate_batch([e])
    assert sessions[0].location_short_name == "Osprey Land's End"
