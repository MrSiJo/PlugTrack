"""Tests for the per-car session-synthesis state machine.

Covers every transition in spec §3.6 plus the edge cases:
- sub-poll-interval (PLUGGED_IN → CHARGING_DONE in one step)
- stale telemetry (carCapturedTimestamp unchanged)
- error states during CHARGING
- top-up resume (CHARGING_DONE → CHARGING opens NEW session, not new plug-in)
- unknown enum value (no-op + caller logs)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugtrack.plugins.pycupra.models import VehicleState
from plugtrack.services.session_synthesiser import StateMachine
from plugtrack.services.sync_orchestrator import CarSyncState


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=offset_seconds
    )


def _vehicle(
    *,
    cable: bool,
    charging: bool,
    soc: int,
    raw: str = "",
    power_kw: float | None = None,
    odo: int | None = 12345,
    captured_at: datetime | None = None,
) -> VehicleState:
    return VehicleState(
        battery_level=soc,
        charging=charging,
        charging_state=charging,
        charging_state_raw=raw,
        charging_power=power_kw,
        charging_time_left=None,
        target_soc=80,
        charging_cable_connected=cable,
        charging_cable_locked=cable,
        external_power=cable,
        energy_flow="charging" if charging else None,
        vehicle_online=True,
        last_connected=captured_at or _ts(),
        distance_km=odo,
        electric_range_km=200,
        position=None,
        car_captured_timestamp=captured_at or _ts(),
    )


# ---------------------------------------------------------------------------
# Spec §3.6 transition table — one test per row.
# ---------------------------------------------------------------------------


def test_idle_to_plugged_in() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="IDLE", last_soc=40)
    tel = _vehicle(cable=True, charging=False, soc=40, captured_at=_ts(60))
    tr = sm.step(prev, tel)
    assert tr.open_plug_in is not None
    assert tr.open_plug_in["plug_in_soc"] == 40
    assert tr.open_session is None
    assert tr.state_observed == "PLUGGED_IN"


def test_plugged_in_to_charging() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="PLUGGED_IN", last_soc=40, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=True,
        soc=41,
        raw="charging",
        power_kw=7.0,
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.open_session is not None
    assert tr.open_session["start_soc"] == 41
    assert tr.open_session["charging_type"] == "ac"
    assert tr.close_session is None
    assert tr.state_observed == "CHARGING"


def test_charging_to_charging_done() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="CHARGING", last_soc=60, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=False,
        soc=80,
        raw="readyForCharging",
        captured_at=_ts(120),
    )
    tr = sm.step(prev, tel)
    assert tr.close_session is not None
    assert tr.close_session["end_soc"] == 80
    assert tr.close_session["interrupted"] is False
    assert tr.open_session is None
    assert tr.state_observed == "CHARGING_DONE"


def test_charging_error_state_closes_with_interrupted() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="CHARGING", last_soc=55, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=True,
        soc=58,
        raw="error_xyz",
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.error_session is not None
    assert tr.error_session["interrupted"] is True
    assert tr.error_session["error_reason"] == "error_xyz"
    assert tr.error_session["end_soc"] == 58


def test_charging_done_to_charging_topup_opens_new_session() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="CHARGING_DONE", last_soc=80, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=True,
        soc=80,
        raw="charging",
        power_kw=7.0,
        captured_at=_ts(120),
    )
    tr = sm.step(prev, tel)
    # NEW session opens — but no new plug_in_record (cable was already in).
    assert tr.open_session is not None
    assert tr.open_session["start_soc"] == 80
    assert tr.open_plug_in is None
    assert tr.state_observed == "CHARGING"


def test_any_to_idle_closes_plug_in_and_session() -> None:
    sm = StateMachine()
    # Was charging — cable yanked.
    prev = CarSyncState(last_state="CHARGING", last_soc=70, last_car_captured_timestamp=_ts())
    tel = _vehicle(cable=False, charging=False, soc=72, captured_at=_ts(60))
    tr = sm.step(prev, tel)
    assert tr.close_plug_in is not None
    assert tr.close_plug_in["plug_out_soc"] == 72
    # Mid-charge interruption → session also closes with interrupted=True.
    assert tr.close_session is not None
    assert tr.close_session["interrupted"] is True
    assert tr.state_observed == "IDLE"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_sub_poll_interval_plugged_to_done_emits_open_and_close() -> None:
    """PLUGGED_IN → CHARGING_DONE in one step: open + close in same poll.

    Triggered by an unambiguous "done" signal
    (chargePurposeReachedAndConservation / conservation). `start_soc`
    comes from the cached prev.last_soc; `end_soc` from current telemetry.
    """
    sm = StateMachine()
    prev = CarSyncState(last_state="PLUGGED_IN", last_soc=70, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=False,
        soc=80,
        raw="chargePurposeReachedAndConservation",
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.open_session is not None
    assert tr.close_session is not None
    assert tr.open_session["start_soc"] == 70  # cached prev.last_soc
    assert tr.close_session["end_soc"] == 80
    assert tr.state_observed == "CHARGING_DONE"


def test_sub_poll_interval_falls_back_to_current_soc_when_prev_unknown() -> None:
    """If prev.last_soc is None, sub-poll start_soc falls back to telemetry."""
    sm = StateMachine()
    prev = CarSyncState(
        last_state="PLUGGED_IN",
        last_soc=None,
        last_car_captured_timestamp=_ts(),
    )
    tel = _vehicle(
        cable=True,
        charging=False,
        soc=80,
        raw="conservation",
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.open_session is not None
    assert tr.open_session["start_soc"] == 80


def test_stale_telemetry_no_change() -> None:
    sm = StateMachine()
    same_ts = _ts(60)
    prev = CarSyncState(
        last_state="CHARGING",
        last_soc=55,
        last_car_captured_timestamp=same_ts,
    )
    tel = _vehicle(cable=True, charging=True, soc=99, raw="charging", captured_at=same_ts)
    tr = sm.step(prev, tel)
    assert tr.no_change is True
    assert tr.state_observed == "CHARGING"
    assert tr.open_session is None
    assert tr.close_session is None


def test_unknown_enum_returns_no_change_with_value() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="PLUGGED_IN", last_soc=40, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=False,
        soc=40,
        raw="future_state_42",
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.no_change is True
    assert tr.unknown_state == "future_state_42"
    assert tr.state_observed == "PLUGGED_IN"


def test_idle_to_idle_no_change() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="IDLE", last_soc=50, last_car_captured_timestamp=_ts())
    tel = _vehicle(cable=False, charging=False, soc=50, captured_at=_ts(60))
    tr = sm.step(prev, tel)
    assert tr.no_change is True
    assert tr.state_observed == "IDLE"


def test_charging_high_power_classified_dc() -> None:
    sm = StateMachine()
    prev = CarSyncState(last_state="PLUGGED_IN", last_soc=20, last_car_captured_timestamp=_ts())
    tel = _vehicle(
        cable=True,
        charging=True,
        soc=22,
        raw="charging",
        power_kw=120.0,
        captured_at=_ts(60),
    )
    tr = sm.step(prev, tel)
    assert tr.open_session is not None
    assert tr.open_session["charging_type"] == "dc"


def test_first_poll_no_prev_timestamp_runs_normally() -> None:
    """Stale-telemetry guard must NOT fire on the very first poll."""
    sm = StateMachine()
    prev = CarSyncState()  # everything default
    tel = _vehicle(cable=False, charging=False, soc=50, captured_at=_ts())
    tr = sm.step(prev, tel)
    # IDLE → IDLE (no prev timestamp)
    assert tr.state_observed == "IDLE"
    # no_change because no actual transition
    assert tr.no_change is True
