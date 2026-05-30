"""Frozen dataclasses representing the typed result of the pycupra adapter.

These mirror the fields enumerated in spec §3.5 (`fetch_vehicle_state`).
Distance fields use the `_km` suffix to match the database convention
(everything stored in km; UI converts on render).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class ProviderAuthError(Exception):
    """Raised by the adapter when the provider rejects an authenticated
    request for authorization reasons (not transient network failures).

    The canonical case is a 403 on the garage endpoint, which pycupra
    surfaces as `PyCupraConfigException("No vehicles were found for given
    account!")`. The worker treats this like an auth failure
    (`credentials_invalid`): it sets `auth_invalid`, stops the scheduler
    re-polling, and surfaces a banner in the UI — rather than silently
    bucketing it as `network` and hammering the endpoint indefinitely.
    """


@dataclass(frozen=True)
class Position:
    """A single GPS position snapshot."""

    lat: float
    lng: float
    captured_at: datetime


@dataclass(frozen=True)
class Credentials:
    """Cupra Connect credentials passed into the adapter."""

    username: str
    password: str
    spin: Optional[str] = None
    api_key: Optional[str] = None


@dataclass(frozen=True)
class VehicleState:
    """Typed snapshot of vehicle state coerced from pycupra Vehicle properties.

    Field semantics:
    - `charging` is the boolean from the Dashboard layer ("is the car
      currently drawing power?").
    - `charging_state` is the boolean from `attrs.charging.status.charging`
      ("is the charging system in an active charging mode?"). For most
      cars these line up but they can disagree during transitions.
    - `charging_state_raw` is the underlying string (e.g. `"charging"`,
      `"readyForCharging"`, `"chargePurposeReachedAndConservation"`)
      preserved verbatim for fine-grained discrimination.
    """

    battery_level: int
    charging: bool
    charging_state: bool
    charging_state_raw: str
    charging_power: Optional[float]
    charging_time_left: Optional[int]
    target_soc: Optional[int]
    charging_cable_connected: bool
    charging_cable_locked: Optional[bool]
    external_power: Optional[bool]
    energy_flow: Optional[str]
    vehicle_online: bool
    last_connected: datetime
    distance_km: Optional[int]
    electric_range_km: Optional[int]
    position: Optional[Position]
    car_captured_timestamp: datetime
    charging_mode_raw: Optional[str] = None
    battery_care: Optional[bool] = None
    max_charge_current: Optional[str] = None
    charging_estimated_end_at: Optional[datetime] = None
