"""Unit tests for the curve-backfill pure logic: the shared curve mapper and
the screenshot->session matcher. The CLI's network/DB orchestration is not
exercised here."""

from datetime import UTC, datetime
from types import SimpleNamespace

from plugtrack.scripts.backfill_curves import pick_session
from plugtrack.services.screenshot_commit import map_curve_points


def test_map_curve_points_keeps_edge_zero_power_points():
    """The 0 kW points at each end ARE the rising and falling edges.

    They used to be stripped as "lead-in / cutoff", which deleted the two
    vertical cliffs that make a home/AC charge read as a square top hat
    (prod #37 rendered as a plateau with no start or end).
    """
    pts = [[0.0, 0], [0.2, 62], [1.0, 0]]
    assert map_curve_points(pts, 1320, 55, 90) == [
        [0, 55, 0.0],
        [264, 62, 62.0],
        [1320, 90, 0.0],
    ]


def test_map_curve_points_preserves_an_interior_gap():
    """A mid-charge drop to 0 kW must survive intact, edges included."""
    pts = [[0.0, 0], [0.25, 2.0], [0.44, 0.0], [0.48, 0.0], [0.53, 2.1], [1.0, 0]]
    got = map_curve_points(pts, 21180, 60, 80)
    assert [round(p[2], 2) for p in got] == [0.0, 2.0, 0.0, 0.0, 2.1, 0.0]
    assert got[0][0] == 0, "curve must start at t=0"
    assert got[-1][0] == 21180, "curve must run to the end of the charge"


def test_map_curve_points_none_when_unusable():
    assert map_curve_points(None, 1320, 55, 90) is None
    assert map_curve_points([], 1320, 55, 90) is None
    assert map_curve_points([[0.2, 62]], 0, 55, 90) is None


def test_map_curve_points_none_when_all_zero():
    """An all-zero trace carries no information — still nothing to plot."""
    assert map_curve_points([[0.0, 0], [0.5, 0], [1.0, 0]], 1320, 55, 90) is None


def test_extraction_curve_reads_stored_raw_points():
    """History can be rebuilt offline: the raw [fraction, kw] points the vision
    model returned are persisted on the import row, so restoring the stripped
    edges needs no image and no OpenAI call."""
    from plugtrack.scripts.remap_curves import _extraction_curve

    assert _extraction_curve({"power_curve": [[0.0, 0], [0.5, 2.0]]}) == [
        [0.0, 0],
        [0.5, 2.0],
    ]
    assert _extraction_curve({"power_curve": None}) is None
    assert _extraction_curve({"power_curve": []}) is None
    assert _extraction_curve({}) is None
    assert _extraction_curve(None) is None


def _cs(sid, start, ss, se):
    return SimpleNamespace(id=sid, charge_start_at=start, start_soc=ss, end_soc=se)


def test_pick_session_matches_by_time_within_tolerance():
    cands = [
        _cs(1, datetime(2026, 6, 18, 11, 26), 55, 90),
        _cs(2, datetime(2026, 6, 18, 13, 17), 67, 80),
    ]
    # Screenshot start parsed as UTC-aware, 2 min off the stored naive time.
    ext_start = datetime(2026, 6, 18, 11, 28, tzinfo=UTC)
    assert pick_session(cands, ext_start, 55, 90, 30).id == 1


def test_pick_session_prefers_soc_match_on_time_tie():
    cands = [
        _cs(1, datetime(2026, 6, 18, 11, 26), 40, 50),
        _cs(2, datetime(2026, 6, 18, 11, 26), 55, 90),
    ]
    assert pick_session(cands, datetime(2026, 6, 18, 11, 26), 55, 90, 30).id == 2


def test_pick_session_none_outside_tolerance():
    cands = [_cs(1, datetime(2026, 6, 18, 11, 26), 55, 90)]
    assert pick_session(cands, datetime(2026, 6, 18, 12, 30), 55, 90, 30) is None
