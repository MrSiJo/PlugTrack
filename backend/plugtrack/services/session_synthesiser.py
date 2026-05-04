"""State-machine session synthesiser.

Spec §3.6 transition table → in-memory `Transitions` dataclass that the
orchestrator translates into row-writes + event-bus emissions.

The synthesiser is PURE — it never touches the database. The orchestrator
owns persistence; this module decides what should change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..plugins.pycupra.models import VehicleState
from .sync_orchestrator import CarSyncState


# Known charging_state_raw enum values per pycupra observations + docs.
KNOWN_CHARGING_STATES: frozenset[str] = frozenset(
    {
        "",  # unknown / missing — not an enum but treat as benign
        "charging",
        "readyForCharging",
        "notReadyForCharging",
        "chargePurposeReachedAndConservation",
        "chargePurposeReachedAndNotConservationCharging",
        "conservation",
        "discharging",
    }
)


@dataclass
class Transitions:
    """Side-effects the orchestrator should apply for one poll cycle.

    Each non-None field is a payload dict the orchestrator inserts/updates.
    Multiple fields may be populated when a single poll observes more than
    one transition (sub-poll-interval handling).
    """

    open_plug_in: Optional[dict[str, Any]] = None
    close_plug_in: Optional[dict[str, Any]] = None
    open_session: Optional[dict[str, Any]] = None
    close_session: Optional[dict[str, Any]] = None
    error_session: Optional[dict[str, Any]] = None
    no_change: bool = False
    unknown_state: Optional[str] = None
    state_observed: Optional[str] = None  # post-transition state for cadence


def derive_state(telemetry: VehicleState, prev_state: str) -> str:
    """Map a typed telemetry snapshot to one of the four state-machine states."""
    if not telemetry.charging_cable_connected:
        return "IDLE"
    if telemetry.charging:
        return "CHARGING"
    # Cable connected, not actively charging.
    raw = telemetry.charging_state_raw or ""
    # readyForCharging while previously charging means the car has
    # reached its target / paused.
    is_done_signal = raw in {
        "readyForCharging",
        "chargePurposeReachedAndConservation",
        "chargePurposeReachedAndNotConservationCharging",
        "conservation",
    }
    if prev_state == "CHARGING" and is_done_signal:
        return "CHARGING_DONE"
    if prev_state == "CHARGING_DONE" and is_done_signal:
        return "CHARGING_DONE"
    # Sub-poll-interval: prev=PLUGGED_IN and we see an unambiguous "done"
    # signal (chargePurposeReachedAndConservation et al). The car must
    # have charged AND finished between polls. derive_state surfaces this
    # as CHARGING_DONE so the synthesiser emits both open + close.
    # `readyForCharging` alone is ambiguous from PLUGGED_IN (the car is
    # simply ready but never charged), so we only trigger on the
    # conservation/reached signals.
    if prev_state == "PLUGGED_IN" and raw in {
        "chargePurposeReachedAndConservation",
        "chargePurposeReachedAndNotConservationCharging",
        "conservation",
    }:
        return "CHARGING_DONE"
    return "PLUGGED_IN"


class StateMachine:
    """Stateless transition engine — call `step()` per poll."""

    def step(self, prev: CarSyncState, telemetry: VehicleState) -> Transitions:
        # ---- Stale-telemetry short-circuit ----
        if (
            prev.last_car_captured_timestamp is not None
            and telemetry.car_captured_timestamp == prev.last_car_captured_timestamp
        ):
            return Transitions(no_change=True, state_observed=prev.last_state)

        raw = telemetry.charging_state_raw or ""

        # ---- Unknown enum: benign no-op + caller logs ----
        if raw and raw not in KNOWN_CHARGING_STATES and not raw.startswith("error"):
            return Transitions(
                no_change=True,
                state_observed=prev.last_state,
                unknown_state=raw,
            )

        # ---- Error state during CHARGING ----
        if raw.startswith("error") and prev.last_state == "CHARGING":
            return Transitions(
                error_session={
                    "charge_end_at": telemetry.car_captured_timestamp,
                    "end_soc": telemetry.battery_level,
                    "error_reason": raw,
                    "interrupted": True,
                },
                # Stay in CHARGING semantically per spec table; cadence
                # then transitions on next poll once cable disconnects.
                state_observed="CHARGING",
            )

        new_state = derive_state(telemetry, prev.last_state)
        prev_state = prev.last_state

        tr = Transitions(state_observed=new_state)

        # ---- IDLE → PLUGGED_IN ----
        if prev_state == "IDLE" and new_state == "PLUGGED_IN":
            tr.open_plug_in = {
                "plug_in_at": telemetry.car_captured_timestamp,
                "plug_in_soc": telemetry.battery_level,
                "plug_in_odometer_km": telemetry.distance_km,
            }
            return tr

        # ---- IDLE → CHARGING (sub-poll-interval: missed PLUGGED_IN) ----
        if prev_state == "IDLE" and new_state == "CHARGING":
            tr.open_plug_in = {
                "plug_in_at": telemetry.car_captured_timestamp,
                "plug_in_soc": telemetry.battery_level,
                "plug_in_odometer_km": telemetry.distance_km,
            }
            tr.open_session = {
                "charge_start_at": telemetry.car_captured_timestamp,
                "start_soc": telemetry.battery_level,
                "charging_type": _charging_type_from_power(telemetry.charging_power),
                "charging_mode": "unknown",
                "odometer_at_session_km": telemetry.distance_km,
            }
            return tr

        # ---- PLUGGED_IN → CHARGING ----
        if prev_state == "PLUGGED_IN" and new_state == "CHARGING":
            tr.open_session = {
                "charge_start_at": telemetry.car_captured_timestamp,
                "start_soc": telemetry.battery_level,
                "charging_type": _charging_type_from_power(telemetry.charging_power),
                "charging_mode": "unknown",
                "odometer_at_session_km": telemetry.distance_km,
            }
            return tr

        # ---- CHARGING → CHARGING_DONE ----
        if prev_state == "CHARGING" and new_state == "CHARGING_DONE":
            tr.close_session = {
                "charge_end_at": telemetry.car_captured_timestamp,
                "end_soc": telemetry.battery_level,
                "interrupted": False,
            }
            return tr

        # ---- PLUGGED_IN → CHARGING_DONE (sub-poll-interval) ----
        # Charge started AND ended between two polls: synthesise an
        # open+close in one step using the cached SoC as start.
        if prev_state == "PLUGGED_IN" and new_state == "CHARGING_DONE":
            start_soc = prev.last_soc if prev.last_soc is not None else telemetry.battery_level
            tr.open_session = {
                "charge_start_at": telemetry.car_captured_timestamp,
                "start_soc": start_soc,
                "charging_type": _charging_type_from_power(telemetry.charging_power),
                "charging_mode": "unknown",
                "odometer_at_session_km": telemetry.distance_km,
            }
            tr.close_session = {
                "charge_end_at": telemetry.car_captured_timestamp,
                "end_soc": telemetry.battery_level,
                "interrupted": False,
            }
            return tr

        # ---- CHARGING_DONE → CHARGING (top-up resume) ----
        # Same plug-in, brand-new session row. Orchestrator must reuse
        # the existing plug_in_record_id and NOT open a new plug_in.
        if prev_state == "CHARGING_DONE" and new_state == "CHARGING":
            tr.open_session = {
                "charge_start_at": telemetry.car_captured_timestamp,
                "start_soc": telemetry.battery_level,
                "charging_type": _charging_type_from_power(telemetry.charging_power),
                "charging_mode": "unknown",
                "odometer_at_session_km": telemetry.distance_km,
            }
            return tr

        # ---- ANY → IDLE (cable removed) ----
        if prev_state != "IDLE" and new_state == "IDLE":
            close_payload = {
                "plug_out_at": telemetry.car_captured_timestamp,
                "plug_out_soc": telemetry.battery_level,
                "plug_out_odometer_km": telemetry.distance_km,
            }
            tr.close_plug_in = close_payload
            # If we were mid-charge, also close the session as interrupted.
            if prev_state == "CHARGING":
                tr.close_session = {
                    "charge_end_at": telemetry.car_captured_timestamp,
                    "end_soc": telemetry.battery_level,
                    "interrupted": True,
                }
            return tr

        # ---- No actual transition ----
        if new_state == prev_state:
            return Transitions(no_change=True, state_observed=new_state)

        # Fallback — shouldn't hit, but be defensive.
        return Transitions(no_change=True, state_observed=new_state)


def _charging_type_from_power(power_kw: Optional[float]) -> str:
    """Heuristic: > 25 kW is DC, anything else AC; None → unknown."""
    if power_kw is None:
        return "unknown"
    return "dc" if power_kw > 25.0 else "ac"
