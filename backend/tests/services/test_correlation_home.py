# backend/tests/services/test_correlation_home.py
from plugtrack.services.screenshot_extraction import Extraction
from plugtrack.services.screenshot_correlation import correlate


def _ex(**kw):
    base = dict(source="x", has_cost=False, energy_kwh=None, cost_total_pence=None,
                cost_per_kwh_pence=None, start_at=None, end_at=None, soc_start=None,
                soc_end=None, location_name=None, location_address=None, network=None,
                peak_kw=None, confidence=0.9)
    base.update(kw)
    return Extraction(**base)


def test_mycupra_plus_granny_merge_to_one_session():
    mycupra = _ex(source="mycupra", soc_start=67, soc_end=80,
                  start_at="2026-06-15T19:27:00", end_at="2026-06-16T06:59:00")
    granny = _ex(source="granny", energy_kwh=9.3,
                 start_at="2026-06-15T19:30:00", end_at="2026-06-16T04:01:00")
    merged = correlate([mycupra, granny])
    assert len(merged) == 1
    m = merged[0]
    assert m.energy_kwh == 9.3            # delivered, from granny
    assert m.soc_start == 67 and m.soc_end == 80  # from MyCupra
    assert {"granny", "mycupra"} <= set(m.source_kinds)


def test_text_note_with_location_carries_location_name():
    note = _ex(source="text", energy_kwh=9.3, location_name="home",
               start_at="2026-06-15T19:27:00")
    [m] = correlate([note])
    assert m.energy_kwh == 9.3 and m.location_name == "home"
