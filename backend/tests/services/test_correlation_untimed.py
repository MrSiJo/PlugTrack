from plugtrack.services.screenshot_correlation import correlate, correlate_batch
from plugtrack.services.screenshot_extraction import Extraction


def _ex(**kw):
    base = dict(
        source="x", has_cost=False, energy_kwh=None, cost_total_pence=None,
        cost_per_kwh_pence=None, start_at=None, end_at=None, soc_start=None,
        soc_end=None, location_name=None, location_address=None, network=None,
        peak_kw=None, confidence=0.9,
    )
    base.update(kw)
    return Extraction(**base)


def test_untimed_attaches_to_single_timed_charge():
    mycupra = _ex(source="mycupra", soc_start=67, soc_end=80,
                  start_at="2026-06-15T19:27:00", end_at="2026-06-16T06:59:00")
    granny = _ex(source="granny", energy_kwh=9.3)  # no timestamps
    sessions, unplaceable = correlate_batch([mycupra, granny])
    assert len(sessions) == 1 and unplaceable == []
    m = sessions[0]
    assert m.energy_kwh == 9.3                 # delivered, from granny
    assert m.soc_start == 67 and m.soc_end == 80   # from MyCupra
    assert {"granny", "mycupra"} <= set(m.source_kinds)


def test_untimed_alone_is_unplaceable():
    granny = _ex(source="granny", energy_kwh=9.3)
    sessions, unplaceable = correlate_batch([granny])
    assert sessions == []
    assert len(unplaceable) == 1 and unplaceable[0] is granny


def test_untimed_ambiguous_with_multiple_timed_charges():
    a = _ex(source="mycupra", soc_start=10, soc_end=40, start_at="2026-06-10T08:00:00",
            end_at="2026-06-10T09:00:00")
    b = _ex(source="mycupra", soc_start=50, soc_end=80, start_at="2026-06-12T20:00:00",
            end_at="2026-06-12T22:00:00")
    granny = _ex(source="granny", energy_kwh=9.3)  # which charge? ambiguous
    sessions, unplaceable = correlate_batch([a, b, granny])
    assert len(sessions) == 2          # the two timed charges stay split
    assert len(unplaceable) == 1 and unplaceable[0] is granny


def test_correlate_delegates_to_batch():
    mycupra = _ex(source="mycupra", soc_start=67, soc_end=80, start_at="2026-06-15T19:27:00")
    granny = _ex(source="granny", energy_kwh=9.3)
    assert len(correlate([mycupra, granny])) == 1
