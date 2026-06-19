"""Unit tests for the curve-backfill pure logic: the shared curve mapper and
the screenshot->session matcher. The CLI's network/DB orchestration is not
exercised here."""
from datetime import datetime, timezone
from types import SimpleNamespace

from plugtrack.scripts.backfill_curves import pick_session
from plugtrack.services.screenshot_commit import map_curve_points


def test_map_curve_points_maps_and_strips_zero_power():
    # Leading/trailing zero-power points (lead-in / cutoff) are dropped; the
    # middle point maps fraction->seconds and interpolates SoC.
    pts = [[0.0, 0], [0.2, 62], [1.0, 0]]
    assert map_curve_points(pts, 1320, 55, 90) == [[264, 62, 62.0]]


def test_map_curve_points_none_when_unusable():
    assert map_curve_points(None, 1320, 55, 90) is None
    assert map_curve_points([], 1320, 55, 90) is None
    assert map_curve_points([[0.2, 62]], 0, 55, 90) is None


def _cs(sid, start, ss, se):
    return SimpleNamespace(id=sid, charge_start_at=start, start_soc=ss, end_soc=se)


def test_pick_session_matches_by_time_within_tolerance():
    cands = [
        _cs(1, datetime(2026, 6, 18, 11, 26), 55, 90),
        _cs(2, datetime(2026, 6, 18, 13, 17), 67, 80),
    ]
    # Screenshot start parsed as UTC-aware, 2 min off the stored naive time.
    ext_start = datetime(2026, 6, 18, 11, 28, tzinfo=timezone.utc)
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
