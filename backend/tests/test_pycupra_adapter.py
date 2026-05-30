"""Tests for the pycupra adapter — fully mocked, no live calls.

The fixtures under `tests/fixtures/pycupra/` are SYNTHETIC. They do not
contain real VINs, real GPS, or any data harvested from a real account.

The pycupra Vehicle is mocked via a plain stub object — we never
construct a real `pycupra.Connection`. The full integration check
against a live account lives in Phase 5.6.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugtrack.plugins.pycupra.adapter import fetch_vehicle_state, force_refresh
from plugtrack.plugins.pycupra.models import VehicleState


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pycupra"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_vehicle_stub(payload: dict[str, Any]) -> MagicMock:
    """Wrap a fixture payload as a duck-typed pycupra Vehicle stub.

    Property reads return the payload value directly. The
    `is_<name>_supported` flags default to True so the property reads
    happen; setting a value to None in the fixture makes the coercion
    layer return None.
    """
    vehicle = MagicMock()
    vehicle.vin = payload["vehicle_id"]
    vehicle.unique_id = payload["vehicle_id"]
    vehicle.attrs = payload.get("attrs", {})

    # Map fixture key -> Vehicle property name. distance_km/electric_range_km
    # are stored in km in the fixture; the Vehicle property is `distance` /
    # `electric_range` (already km from pycupra).
    direct_attrs = {
        "battery_level": payload["battery_level"],
        "charging": payload["charging"],
        "charging_state": payload["charging_state"],
        "charging_power": payload["charging_power"],
        "charging_time_left": payload["charging_time_left"],
        "target_soc": payload["target_soc"],
        "charging_cable_connected": payload["charging_cable_connected"],
        "charging_cable_locked": payload["charging_cable_locked"],
        "external_power": payload["external_power"],
        "energy_flow": payload["energy_flow"],
        "vehicle_online": payload["vehicle_online"],
        "last_connected": datetime.fromisoformat(payload["last_connected"]),
        "distance": payload["distance_km"],
        "electric_range": payload["electric_range_km"],
        "position": payload["position"],
    }
    for k, v in direct_attrs.items():
        setattr(vehicle, k, v)
        # All properties are reported as supported — the coercion
        # layer handles None values gracefully.
        setattr(vehicle, f"is_{k}_supported", True)

    # The discover/get_* methods are awaitable no-ops in the stub.
    for fn_name in ("discover", "get_charger", "get_statusreport", "get_position", "get_mileage"):
        setattr(vehicle, fn_name, AsyncMock(return_value=None))

    return vehicle


def _build_connection_stub(vehicle: MagicMock) -> MagicMock:
    connection = MagicMock()
    # pycupra's get_vehicles() returns a bool and populates _vehicles.
    connection.get_vehicles = AsyncMock(return_value=True)
    connection._vehicles = [vehicle]
    connection.setRefresh = AsyncMock(return_value=True)
    return connection


@pytest.mark.asyncio
async def test_fetch_vehicle_state_charging():
    payload = _load_fixture("vehicle_charging.json")
    vehicle = _build_vehicle_stub(payload)
    connection = _build_connection_stub(vehicle)

    # fetch_vehicle_state now returns (VehicleState, getter_call_count).
    state, getter_calls = await fetch_vehicle_state(connection, payload["vehicle_id"])

    assert isinstance(state, VehicleState)
    assert getter_calls == 5  # one per getter in the tuple
    assert state.battery_level == 47
    assert state.charging is True
    assert state.charging_state is True
    # Critical: charging_state (bool) and charging_state_raw (str) must
    # both be populated from distinct sources.
    assert state.charging_state_raw == "charging"
    assert state.charging_power == pytest.approx(75.4)
    assert state.target_soc == 80
    assert state.charging_cable_connected is True
    assert state.charging_cable_locked is True
    assert state.external_power is True
    assert state.energy_flow == "on"
    assert state.distance_km == 12345
    assert state.electric_range_km == 184
    assert state.position is not None
    assert state.position.lat == pytest.approx(50.8503)
    assert state.position.lng == pytest.approx(-0.1387)
    assert state.car_captured_timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_fetch_vehicle_state_idle():
    payload = _load_fixture("vehicle_idle.json")
    vehicle = _build_vehicle_stub(payload)
    connection = _build_connection_stub(vehicle)

    state, getter_calls = await fetch_vehicle_state(connection, payload["vehicle_id"])

    assert getter_calls == 5
    assert state.charging is False
    assert state.charging_state is False
    assert state.charging_state_raw == "off"
    assert state.charging_cable_connected is False
    assert state.charging_power is None
    assert state.position is None


@pytest.mark.asyncio
async def test_fetch_vehicle_state_charge_done():
    payload = _load_fixture("vehicle_done.json")
    vehicle = _build_vehicle_stub(payload)
    connection = _build_connection_stub(vehicle)

    state, getter_calls = await fetch_vehicle_state(connection, payload["vehicle_id"])

    # Charge complete: bool flags are False but raw enum says
    # "readyForCharging" — the fine-grained discriminator the
    # synthesis layer needs.
    assert getter_calls == 5
    assert state.charging is False
    assert state.charging_state is False
    assert state.charging_state_raw == "readyForCharging"
    assert state.battery_level == 80
    assert state.charging_cable_connected is True


@pytest.mark.asyncio
async def test_fetch_vehicle_state_raises_for_unknown_vehicle():
    payload = _load_fixture("vehicle_idle.json")
    vehicle = _build_vehicle_stub(payload)
    connection = _build_connection_stub(vehicle)

    with pytest.raises(ValueError, match="not found"):
        await fetch_vehicle_state(connection, "TESTVIN0000000099")


@pytest.mark.asyncio
async def test_force_refresh_passes_through_to_connection():
    connection = MagicMock()
    connection.setRefresh = AsyncMock(return_value=True)

    result = await force_refresh(connection, "TESTVIN0000000001")

    assert result is True
    connection.setRefresh.assert_awaited_once_with("TESTVIN0000000001")


# ---------------------------------------------------------------------------
# pycupra exception → ProviderAuthError translation
#
# A 403 on the garage endpoint surfaces as PyCupraConfigException
# ("No vehicles were found for given account!"). That is an authorization
# failure, not a transient network error, so the adapter re-raises it as
# ProviderAuthError for the worker to classify as credentials_invalid.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_translates_no_vehicles_to_provider_auth_error():
    from pycupra.exceptions import PyCupraConfigException

    from plugtrack.plugins.pycupra.models import ProviderAuthError

    connection = MagicMock()
    connection.get_vehicles = AsyncMock(
        side_effect=PyCupraConfigException(
            "No vehicles were found for given account!"
        )
    )

    with pytest.raises(ProviderAuthError):
        await fetch_vehicle_state(connection, "TESTVIN0000000001")


@pytest.mark.asyncio
async def test_fetch_translates_login_failed_to_provider_auth_error():
    from pycupra.exceptions import PyCupraLoginFailedException

    from plugtrack.plugins.pycupra.models import ProviderAuthError

    connection = MagicMock()
    connection.get_vehicles = AsyncMock(
        side_effect=PyCupraLoginFailedException("token rejected")
    )

    with pytest.raises(ProviderAuthError):
        await fetch_vehicle_state(connection, "TESTVIN0000000001")


def test_vehiclestate_has_charge_context_fields_defaulting_none():
    import datetime as dt
    from plugtrack.plugins.pycupra.models import VehicleState
    now = dt.datetime.now(dt.timezone.utc)
    vs = VehicleState(
        battery_level=50, charging=False, charging_state=False,
        charging_state_raw="", charging_power=None, charging_time_left=None,
        target_soc=None, charging_cable_connected=False,
        charging_cable_locked=None, external_power=None, energy_flow=None,
        vehicle_online=True, last_connected=now, distance_km=None,
        electric_range_km=None, position=None, car_captured_timestamp=now,
    )
    assert vs.charging_mode_raw is None
    assert vs.battery_care is None
    assert vs.max_charge_current is None
    assert vs.charging_estimated_end_at is None


# ---------------------------------------------------------------------------
# Task 2: charge-context coercion helpers + adapter reads
# ---------------------------------------------------------------------------


class _FakeVehicle:
    def __init__(self, **attrs):
        self._a = attrs

    def __getattr__(self, name):
        if name in self._a:
            return self._a[name]
        if name.startswith("is_") and name.endswith("_supported"):
            return name[3:-10] in self._a
        raise AttributeError(name)


def test_normalise_charging_mode():
    from plugtrack.plugins.pycupra.adapter import _normalise_charging_mode
    assert _normalise_charging_mode("Timer") == "timer"      # property is capitalised
    assert _normalise_charging_mode("manual") == "manual"
    assert _normalise_charging_mode("profile") == "profile"
    assert _normalise_charging_mode("Scheduled") == "unknown"  # not a session mode
    assert _normalise_charging_mode(None) == "unknown"


def test_coerce_optional_datetime_handles_aware_and_bad():
    import datetime as dt
    from plugtrack.plugins.pycupra.adapter import _coerce_optional_datetime
    aware = dt.datetime(2026, 5, 30, 8, 0, tzinfo=dt.timezone.utc)
    assert _coerce_optional_datetime(aware) == aware
    assert _coerce_optional_datetime("not-a-date") is None
    assert _coerce_optional_datetime(None) is None
