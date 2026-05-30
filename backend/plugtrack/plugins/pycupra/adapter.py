"""Thin adapter over the pycupra library.

This is the ONLY place in the codebase that imports pycupra. All callers
work with the `VehicleState` / `Position` / `Credentials` dataclasses
(`models.py`) and never see pycupra's `Connection` / `Vehicle` types
beyond the opaque handles passed back and forth.

The adapter does NOT enforce rate-limits — `force_refresh` calls
`Connection.setRefresh` unconditionally; the orchestrator (Phase 4) is
responsible for the 1×/30-min cap to protect the vehicle's 12V battery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pycupra import Connection  # type: ignore[import-untyped]
from pycupra.exceptions import (  # type: ignore[import-untyped]
    PyCupraConfigException,
    PyCupraLoginFailedException,
)

from .models import Credentials, Position, ProviderAuthError, VehicleState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def authenticate(creds: Credentials, token_dir: Path) -> Connection:
    """Sign in to Cupra Connect and return an open `pycupra.Connection`.

    Tokens are persisted to `{token_dir}/pycupra_credentials.json` (the
    library's own JSON cache format) so subsequent runs can refresh
    instead of doing a full OAuth round-trip.
    """
    import aiohttp

    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / "pycupra_credentials.json"

    session = aiohttp.ClientSession()
    connection = Connection(
        session=session,
        username=creds.username,
        password=creds.password,
        spin=creds.spin,
        nightlyUpdateReductionMode=False,
    )
    await connection.doLogin(tokenFile=str(token_path))
    return connection


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read a Vehicle property without raising on `is_<x>_supported=False`.

    pycupra's Vehicle properties tend to raise when their backing data is
    missing. Probe via the `is_<name>_supported` flag where available.
    """
    is_supported = getattr(obj, f"is_{name}_supported", None)
    if is_supported is False:
        return default
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return _coerce_bool(value)


_CHARGING_MODE_VALUES = {"manual", "timer", "profile"}


def _normalise_charging_mode(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip().lower() in _CHARGING_MODE_VALUES:
        return raw.strip().lower()
    return "unknown"


def _coerce_optional_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return _utcnow()


def _read_charging_state_raw(vehicle: Any) -> str:
    """Reach into `attrs.charging.status.charging.state` for the raw enum."""
    try:
        attrs = getattr(vehicle, "attrs", None) or {}
        charging = attrs.get("charging", {}) if isinstance(attrs, dict) else {}
        status = charging.get("status", {}) if isinstance(charging, dict) else {}
        inner = status.get("charging", {}) if isinstance(status, dict) else {}
        state = inner.get("state") if isinstance(inner, dict) else None
        if isinstance(state, str):
            return state
    except Exception:
        pass
    return ""


def _read_position(vehicle: Any) -> Optional[Position]:
    pos = _safe_attr(vehicle, "position")
    if not pos or not isinstance(pos, dict):
        return None
    lat = pos.get("lat") if "lat" in pos else pos.get("latitude")
    lng = pos.get("lng") if "lng" in pos else pos.get("longitude")
    if lat is None or lng is None:
        return None
    captured_raw = pos.get("carCapturedTimestamp") or pos.get("captured_at")
    captured_at = _coerce_datetime(captured_raw)
    try:
        return Position(lat=float(lat), lng=float(lng), captured_at=captured_at)
    except (TypeError, ValueError):
        return None


def _read_car_captured_timestamp(vehicle: Any) -> datetime:
    try:
        attrs = getattr(vehicle, "attrs", None) or {}
        if isinstance(attrs, dict):
            charging = attrs.get("charging", {})
            if isinstance(charging, dict):
                ts = charging.get("carCapturedTimestamp")
                if ts:
                    return _coerce_datetime(ts)
    except Exception:
        pass
    return _utcnow()


async def fetch_vehicle_state(
    connection: Connection, vehicle_id: str
) -> tuple["VehicleState", int]:
    """Pull a typed snapshot of the named vehicle's state.

    Triggers ``discover()`` + the relevant ``get_*`` calls so the Vehicle's
    ``attrs`` cache is populated, then reads via the property API and
    coerces into our ``VehicleState`` dataclass.

    Returns a ``(VehicleState, getter_calls)`` tuple where *getter_calls* is
    the number of individual getter functions that succeeded.  The caller
    (the sync worker) records this against the daily quota counter.

    NOTE: All pycupra requests that count against the Cupra API quota MUST
    flow through this function.  If additional pycupra calls are added
    elsewhere in future (e.g. a history endpoint), they must also record
    their count via the same quota mechanism.
    """
    # ``get_vehicles()`` populates ``connection._vehicles`` and returns a bool.
    # The actual Vehicle objects live on ``_vehicles`` (list in pycupra v0.2.x).
    #
    # A 403 on the garage endpoint (e.g. Cupra's 2026-05-20 API change vs
    # an outdated pycupra) surfaces here as PyCupraConfigException
    # ("No vehicles were found for given account!"), and a rejected token as
    # PyCupraLoginFailedException. Both are authorization failures, not
    # transient network errors — re-raise as ProviderAuthError so the worker
    # flags auth_invalid and stops the scheduler hammering a dead endpoint.
    try:
        await connection.get_vehicles()
    except (PyCupraConfigException, PyCupraLoginFailedException) as exc:
        raise ProviderAuthError(str(exc)) from exc
    raw = getattr(connection, "_vehicles", None)
    if isinstance(raw, dict):
        candidates = list(raw.values())
    elif isinstance(raw, list):
        candidates = raw
    else:
        candidates = []
    vehicle = None
    for candidate in candidates:
        candidate_id = (
            getattr(candidate, "vin", None)
            or getattr(candidate, "_vin", None)
            or getattr(candidate, "unique_id", None)
        )
        if candidate_id == vehicle_id:
            vehicle = candidate
            break
    if vehicle is None:
        known = [
            getattr(c, "vin", None) or getattr(c, "_vin", None) for c in candidates
        ]
        raise ValueError(
            f"vehicle {vehicle_id!r} not found in pycupra response; "
            f"available VINs: {known!r}"
        )

    # Populate the underlying attrs cache. Each call is best-effort —
    # cars may not support every endpoint.  Count successful calls so the
    # worker can record them against the daily quota budget.
    getter_calls = 0
    for fn_name in ("discover", "get_charger", "get_statusreport", "get_position", "get_mileage"):
        fn = getattr(vehicle, fn_name, None)
        if fn is None:
            continue
        try:
            result = fn()
            if hasattr(result, "__await__"):
                await result
            getter_calls += 1
        except Exception:
            # Adapter is permissive — let the orchestrator surface
            # missing data via downstream None values rather than
            # exploding mid-fetch.
            continue

    return VehicleState(
        battery_level=_coerce_int(_safe_attr(vehicle, "battery_level")) or 0,
        charging=_coerce_bool(_safe_attr(vehicle, "charging")),
        charging_state=_coerce_bool(_safe_attr(vehicle, "charging_state")),
        charging_state_raw=_read_charging_state_raw(vehicle),
        charging_power=_coerce_float(_safe_attr(vehicle, "charging_power")),
        charging_time_left=_coerce_int(_safe_attr(vehicle, "charging_time_left")),
        target_soc=_coerce_int(_safe_attr(vehicle, "target_soc")),
        charging_cable_connected=_coerce_bool(
            _safe_attr(vehicle, "charging_cable_connected")
        ),
        charging_cable_locked=_coerce_optional_bool(
            _safe_attr(vehicle, "charging_cable_locked")
        ),
        external_power=_coerce_optional_bool(_safe_attr(vehicle, "external_power")),
        energy_flow=_safe_attr(vehicle, "energy_flow"),
        vehicle_online=_coerce_bool(_safe_attr(vehicle, "vehicle_online")),
        last_connected=_coerce_datetime(_safe_attr(vehicle, "last_connected")),
        distance_km=_coerce_int(_safe_attr(vehicle, "distance")),
        electric_range_km=_coerce_int(_safe_attr(vehicle, "electric_range")),
        position=_read_position(vehicle),
        car_captured_timestamp=_read_car_captured_timestamp(vehicle),
        charging_mode_raw=_normalise_charging_mode(
            _safe_attr(vehicle, "charging_mode")
        ),
        battery_care=_coerce_optional_bool(
            _safe_attr(vehicle, "charging_battery_care")
        ),
        max_charge_current=(
            str(_safe_attr(vehicle, "charge_max_ampere"))
            if _safe_attr(vehicle, "charge_max_ampere") not in (None, "")
            else None
        ),
        charging_estimated_end_at=_coerce_optional_datetime(
            _safe_attr(vehicle, "charging_estimated_end_time")
        ),
    ), getter_calls


async def force_refresh(connection: Connection, vehicle_id: str) -> bool:
    """Wake the car via the cloud "request fresh data" endpoint.

    Drains the 12V battery slightly; the orchestrator must enforce a
    per-vehicle rate-limit (1× per 30 minutes). The adapter is a thin
    pass-through.
    """
    result = await connection.setRefresh(vehicle_id)
    return bool(result)
