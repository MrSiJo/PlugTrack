"""PlugTrack v2 — Phase 0 pycupra discovery harness.

This is a one-shot, read-only probe. It authenticates against the developer's
real My Cupra account, walks pycupra's public surface, and writes JSON
captures plus a pre-populated findings markdown document under ``docs/``.

Outputs (all under ``docs/`` which is gitignored):

    docs/probe_output/00_summary.json            run metadata
    docs/probe_output/01_user_data.json          redacted account info
    docs/probe_output/02_vehicles.json           redacted vehicle list
    docs/probe_output/03_vehicle_<vinhash>/      one file per get_* method
    docs/probe_output/04_token_inspection.json   JWT exp + cache file shape
    docs/probe_output/05_endpoint_inventory.json which endpoints worked
    docs/probe_output/06_history_probe.json      charging history surface scan
    docs/probe_output/07_rate_limit_probe.json   only if PROBE_RATE_LIMIT=1
    docs/pycupra-findings.md                     pre-filled findings template

Run with:

    python -m pip install pycupra aiohttp python-dotenv
    python scripts/pycupra_probe.py

The probe reads .env.probe from the repo root. Copy .env.probe.example first.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
import traceback
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PROBE = REPO_ROOT / ".env.probe"
OUTPUT_DIR = REPO_ROOT / "docs" / "probe_output"
FINDINGS_PATH = REPO_ROOT / "docs" / "pycupra-findings.md"


# ---------------------------------------------------------------------------
# Bootstrap: load .env.probe before importing optional deps
# ---------------------------------------------------------------------------

def _load_env_probe() -> None:
    if not ENV_PROBE.exists():
        sys.exit(
            f"Missing {ENV_PROBE}. Copy .env.probe.example to .env.probe and fill it in."
        )
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ENV_PROBE)
        return
    except ImportError:
        pass
    # Minimal manual loader so the script still runs without python-dotenv.
    for raw in ENV_PROBE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_KEY_RE = re.compile(
    r"^(access[_-]?token|refresh[_-]?token|id[_-]?token|csrf[_-]?token|secToken|spin)$",
    re.IGNORECASE,
)
LATLON_KEYS = {"latitude", "longitude", "lat", "lon", "lng"}
ADDRESS_KEYS = {
    "street", "houseNumber", "streetNumber", "address", "addressLine",
    "addressLine1", "city", "country", "zip", "zipCode", "postalCode",
    "firstName", "lastName", "name", "salutation",
}
USER_ID_KEYS = {"userId", "user_id", "uuid", "subject", "sub", "customerId"}


def vin_hash(vin: str) -> str:
    return hashlib.sha256(vin.encode("utf-8")).hexdigest()[:8]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def _coarsen_coord(value: Any) -> Any:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return round(f)  # whole-degree resolution; ~111km precision


def redact(obj: Any, key: str | None = None) -> Any:
    """Best-effort recursive redaction of personal data.

    Strategy:
      - Token-bearing keys: replace string value with "<redacted:N-chars>".
      - VINs anywhere: replace with "vin:<8-char-hash>".
      - Emails anywhere: mask local part.
      - Lat/lon: round to integer degree.
      - Address-shaped keys: replace with "<redacted>".
      - User-id-shaped keys: replace with "<user-id>".
      - Otherwise recurse.
    """
    if isinstance(obj, dict):
        return {k: redact(v, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        if key and TOKEN_KEY_RE.match(key):
            return f"<redacted:{len(obj)}-chars>"
        if key in ADDRESS_KEYS:
            return "<redacted>"
        if key in USER_ID_KEYS:
            return "<user-id>"
        s = obj
        s = VIN_RE.sub(lambda m: f"vin:{vin_hash(m.group(0))}", s)
        s = EMAIL_RE.sub(lambda m: mask_email(m.group(0)), s)
        return s
    if isinstance(obj, (int, float)) and key and key.lower() in LATLON_KEYS:
        return _coarsen_coord(obj)
    return obj


# ---------------------------------------------------------------------------
# JSON-safe coercion (pycupra returns datetime / Decimal / objects with
# __dict__). Coerce before redact so the redact pass sees plain types.
# ---------------------------------------------------------------------------

def to_jsonable(obj: Any, _depth: int = 0) -> Any:
    if _depth > 12:
        return f"<truncated:{type(obj).__name__}>"
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v, _depth + 1) for v in obj]
    if hasattr(obj, "__dict__"):
        return {
            k: to_jsonable(v, _depth + 1)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }
    return repr(obj)


# ---------------------------------------------------------------------------
# Schema sketcher — given a JSON-able value, produce a type-only outline.
# ---------------------------------------------------------------------------

def schema_of(obj: Any, _depth: int = 0) -> Any:
    if _depth > 6:
        return "..."
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        if len(obj) > 24:
            return "string(long)"
        return "string"
    if isinstance(obj, list):
        if not obj:
            return ["empty"]
        return [schema_of(obj[0], _depth + 1)]
    if isinstance(obj, dict):
        return OrderedDict(
            (k, schema_of(v, _depth + 1)) for k, v in list(obj.items())[:60]
        )
    return type(obj).__name__


# ---------------------------------------------------------------------------
# JWT inspection (no signature verification — read-only field extraction)
# ---------------------------------------------------------------------------

def jwt_exp_info(token: str) -> dict[str, Any]:
    if not token or token.count(".") < 2:
        return {"shape": "non-jwt", "length": len(token) if token else 0}
    try:
        payload_b64 = token.split(".")[1]
        # base64url with possibly missing padding
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        return {"shape": "jwt-but-unparseable", "error": str(exc)}
    out: dict[str, Any] = {"shape": "jwt", "claims_present": sorted(payload.keys())}
    for claim in ("iat", "exp", "nbf", "auth_time"):
        if claim in payload:
            try:
                out[f"{claim}_iso"] = datetime.fromtimestamp(
                    payload[claim], tz=timezone.utc
                ).isoformat()
            except Exception:
                pass
    if "exp" in payload and "iat" in payload:
        out["ttl_seconds"] = int(payload["exp"]) - int(payload["iat"])
    return out


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Vehicle-method enumeration
# ---------------------------------------------------------------------------

# Discovered from pycupra/vehicle.py — async no-arg getters that mutate
# vehicle.attrs. The mapping below records which top-level attrs subtrees
# each method is responsible for populating, based on observed pycupra 0.2.x
# behaviour. Empty list = method has no observed attrs side-effect (either
# unsupported on this account, file-system side-effect like model image, or
# a fan-out method like discover() — see USE_FULL_ATTRS).
VEHICLE_GET_METHODS: tuple[str, ...] = (
    "discover",
    "get_basiccardata",
    "get_mileage",
    "get_statusreport",
    "get_charger",
    "get_climater",
    "get_climatisation_timers",
    "get_departure_timers",
    "get_departure_profiles",
    "get_position",
    "get_trip_statistic",
    "get_preheater",
    "get_maintenance",
    "get_vehicleHealthWarnings",
    "get_modelimageurl",
)

METHOD_TO_ATTR_KEYS: dict[str, tuple[str, ...]] = {
    "discover": (),  # fan-out; capture full attrs
    "get_basiccardata": ("mycar",),
    "get_mileage": ("mileage",),
    "get_statusreport": ("status", "ranges"),
    "get_charger": ("charging",),
    "get_climater": ("climater",),
    "get_climatisation_timers": ("climatisationTimers",),
    "get_departure_timers": ("departureTimers",),
    "get_departure_profiles": ("departureProfiles",),
    "get_position": ("findCarResponse", "lastValidFindCarResponse", "isMoving"),
    "get_trip_statistic": ("tripstatistics",),
    "get_preheater": ("preheater",),
    "get_maintenance": ("maintenance",),
    "get_vehicleHealthWarnings": ("warninglights",),
    "get_modelimageurl": (),  # writes a file; no attrs side-effect
}

USE_FULL_ATTRS: frozenset[str] = frozenset({"discover"})

# Hints we'd hope to find if a server-side charging history exists. None
# of these are documented; the probe records the negative result either way.
HISTORY_HINT_TOKENS = (
    "history", "sessions", "charging_session", "chargingSession",
    "log", "events", "audit",
)


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------

async def run() -> None:
    _load_env_probe()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    inventory: list[dict[str, Any]] = []

    # Imports deferred so missing deps yield a clean error message rather than
    # an ImportError before .env.probe is even loaded.
    try:
        import aiohttp  # type: ignore
        from pycupra import Connection  # type: ignore
    except ImportError as exc:
        sys.exit(
            f"Missing dependency: {exc}. Install with:\n"
            f"  python -m pip install pycupra aiohttp python-dotenv"
        )

    username = os.environ.get("CUPRA_USERNAME", "").strip()
    password = os.environ.get("CUPRA_PASSWORD", "").strip()
    brand = os.environ.get("CUPRA_BRAND", "cupra").strip() or "cupra"
    api_key = os.environ.get("CUPRA_API_KEY", "").strip() or None
    token_file_rel = os.environ.get(
        "CUPRA_TOKEN_FILE", "docs/probe_output/pycupra_credentials.json"
    )
    token_file = (REPO_ROOT / token_file_rel).resolve()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    rate_limit_probe = os.environ.get("PROBE_RATE_LIMIT", "0").strip() == "1"
    history_endpoints_probe = os.environ.get("PROBE_HISTORY_ENDPOINTS", "0").strip() == "1"

    if not username or not password:
        sys.exit("CUPRA_USERNAME and CUPRA_PASSWORD must be set in .env.probe.")

    print(f"[probe] brand={brand} user={mask_email(username)} token_file={token_file}")

    summary: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "brand": brand,
        "user": mask_email(username),
        "token_file": str(token_file.relative_to(REPO_ROOT)),
        "pycupra_version": _detect_pycupra_version(),
        "python_version": sys.version,
    }

    async with aiohttp.ClientSession() as session:
        connection = Connection(session, brand, username, password, False)

        # ---- Step 1: doLogin (timed) -----------------------------------
        login_record: dict[str, Any] = {"endpoint": "Connection.doLogin"}
        t0 = time.monotonic()
        try:
            ok = await connection.doLogin(tokenFile=str(token_file), apiKey=api_key)
            login_record["status"] = "ok" if ok else "failed"
            login_record["returned"] = bool(ok)
        except Exception as exc:
            login_record["status"] = "error"
            login_record["error"] = repr(exc)
            login_record["traceback"] = traceback.format_exc()
        login_record["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        inventory.append(login_record)

        if login_record.get("status") != "ok":
            write_json(OUTPUT_DIR / "05_endpoint_inventory.json", inventory)
            write_json(OUTPUT_DIR / "00_summary.json", {**summary, "login": login_record})
            sys.exit(
                "doLogin failed — see docs/probe_output/05_endpoint_inventory.json. "
                "Aborting before any data calls."
            )

        # ---- Step 2: get_userData --------------------------------------
        user_record: dict[str, Any] = {"endpoint": "Connection.get_userData"}
        t0 = time.monotonic()
        try:
            await connection.get_userData()
            user_record["status"] = "ok"
        except Exception as exc:
            user_record["status"] = "error"
            user_record["error"] = repr(exc)
        user_record["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        inventory.append(user_record)

        user_data = getattr(connection, "_userData", None) or getattr(
            connection, "userData", None
        )
        write_json(
            OUTPUT_DIR / "01_user_data.json",
            redact(to_jsonable(user_data)),
        )

        # ---- Step 3: get_vehicles --------------------------------------
        vehicles_record: dict[str, Any] = {"endpoint": "Connection.get_vehicles"}
        t0 = time.monotonic()
        try:
            await connection.get_vehicles()
            vehicles_record["status"] = "ok"
        except Exception as exc:
            vehicles_record["status"] = "error"
            vehicles_record["error"] = repr(exc)
        vehicles_record["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        inventory.append(vehicles_record)

        vehicles = list(getattr(connection, "vehicles", []) or [])
        summary["vehicle_count"] = len(vehicles)
        vehicles_record["count"] = len(vehicles)

        if not vehicles:
            print("[probe] No vehicles found on this account; skipping per-vehicle calls.")

        # ---- Step 4: per-vehicle endpoint walk -------------------------
        vehicles_serial: list[dict[str, Any]] = []

        for v in vehicles:
            vin = getattr(v, "vin", None) or (getattr(v, "attrs", {}) or {}).get("vin")
            vh = vin_hash(vin) if vin else "unknown"
            vdir = OUTPUT_DIR / f"03_vehicle_{vh}"

            for method_name in VEHICLE_GET_METHODS:
                fn = getattr(v, method_name, None)
                rec: dict[str, Any] = {
                    "endpoint": f"Vehicle.{method_name}",
                    "vin_hash": vh,
                }
                if not callable(fn):
                    rec["status"] = "missing"
                    inventory.append(rec)
                    continue
                t0 = time.monotonic()
                try:
                    result = await fn()
                    rec["status"] = "ok"
                    rec["return_truthy"] = bool(result) if result is not None else None
                except Exception as exc:
                    rec["status"] = "error"
                    rec["error"] = repr(exc)
                rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
                inventory.append(rec)

                # Capture the attrs subtree this method is documented to own.
                # Diff-based capture doesn't work because get_vehicles() / the
                # session token cache pre-populate all top-level keys, so per-
                # method calls only refresh stable values.
                attrs_now = getattr(v, "attrs", {}) or {}
                expected_keys = METHOD_TO_ATTR_KEYS.get(method_name, ())
                if method_name in USE_FULL_ATTRS or not expected_keys:
                    captured: dict[str, Any] = (
                        {k: to_jsonable(v_) for k, v_ in attrs_now.items()}
                        if method_name in USE_FULL_ATTRS
                        else {}
                    )
                    capture_strategy = "full_attrs" if method_name in USE_FULL_ATTRS else "no_attrs_mapping"
                else:
                    captured = {
                        k: to_jsonable(attrs_now[k])
                        for k in expected_keys
                        if k in attrs_now
                    }
                    capture_strategy = "mapped_subtree"
                missing_expected = [k for k in expected_keys if k not in attrs_now]
                redacted = redact(captured)
                write_json(
                    vdir / f"{method_name}.json",
                    {
                        "method": method_name,
                        "elapsed_ms": rec["elapsed_ms"],
                        "status": rec["status"],
                        "capture_strategy": capture_strategy,
                        "expected_attr_keys": list(expected_keys),
                        "captured_attr_keys": sorted(captured.keys()),
                        "missing_expected_keys": missing_expected,
                        "data": redacted,
                        "schema": schema_of(redacted),
                    },
                )

            # Final full attrs dump for this vehicle (post-walk).
            attrs_final = redact(to_jsonable(getattr(v, "attrs", {}) or {}))
            write_json(vdir / "_final_attrs.json", {
                "schema": schema_of(attrs_final),
                "data": attrs_final,
            })

            # Now that per-vehicle calls have populated metadata, build the
            # vehicles list entry with real model / year / capability info.
            attrs_post = getattr(v, "attrs", {}) or {}
            mycar = attrs_post.get("mycar") or {}
            capabilities = attrs_post.get("capabilities")
            if not isinstance(capabilities, dict):
                # Some pycupra versions store capabilities under mycar.
                capabilities = mycar.get("capabilities") if isinstance(mycar, dict) else None
            vehicles_serial.append({
                "vin_hash": vh,
                "model": (
                    attrs_post.get("model")
                    or (mycar.get("model") if isinstance(mycar, dict) else None)
                ),
                "modelYear": (
                    attrs_post.get("modelYear")
                    or (mycar.get("modelYear") if isinstance(mycar, dict) else None)
                ),
                "capabilities_keys": (
                    sorted(capabilities.keys()) if isinstance(capabilities, dict) else None
                ),
                "top_level_attr_keys": sorted(attrs_post.keys()),
            })

        write_json(OUTPUT_DIR / "02_vehicles.json", redact(to_jsonable(vehicles_serial)))

        # ---- Step 4b: Vehicle.<property> dashboard capture --------------
        # The pycupra Dashboard layer exposes named, type-coerced
        # properties (battery_level, charging_state, target_soc, etc.)
        # consumed by the homeassistant-pycupra integration. This is the
        # canonical access pattern for v1; capture each one to see what's
        # actually populated for this vehicle right now.
        for v in vehicles:
            vin = getattr(v, "vin", None) or (getattr(v, "attrs", {}) or {}).get("vin")
            vh = vin_hash(vin) if vin else "unknown"
            vdir = OUTPUT_DIR / f"03_vehicle_{vh}"
            props = _capture_vehicle_properties(v)
            write_json(vdir / "_vehicle_properties.json", props)

        # ---- Step 5: token cache + JWT inspection ----------------------
        token_inspection: dict[str, Any] = {
            "token_file_path": str(token_file.relative_to(REPO_ROOT)),
            "token_file_exists": token_file.exists(),
        }
        if token_file.exists():
            try:
                cache = json.loads(token_file.read_text(encoding="utf-8"))
            except Exception as exc:
                token_inspection["read_error"] = repr(exc)
                cache = {}
            token_inspection["token_file_keys"] = sorted(cache.keys()) if isinstance(cache, dict) else None
            token_inspection["jwt_inspection"] = {
                k: jwt_exp_info(v) for k, v in (cache.items() if isinstance(cache, dict) else [])
                if isinstance(v, str) and v.count(".") >= 2
            }
            try:
                stat = token_file.stat()
                token_inspection["size_bytes"] = stat.st_size
                token_inspection["mtime_iso"] = datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat()
            except Exception:
                pass
        write_json(OUTPUT_DIR / "04_token_inspection.json", token_inspection)

        # ---- Step 6: charging-history surface scan ---------------------
        # pycupra (as of this writing) does not expose a server-side history
        # endpoint; this probe records the negative finding so the user can
        # confirm or refute it on their account version.
        history_probe: dict[str, Any] = {
            "purpose": (
                "Search Connection + Vehicle for any method/attribute whose "
                "name suggests a server-side charging-history list."
            ),
            "hint_tokens": list(HISTORY_HINT_TOKENS),
            "matches_on_connection": _name_matches(connection, HISTORY_HINT_TOKENS),
        }
        if vehicles:
            v0 = vehicles[0]
            history_probe["matches_on_vehicle"] = _name_matches(v0, HISTORY_HINT_TOKENS)
            attrs0 = getattr(v0, "attrs", {}) or {}
            history_probe["vehicle_attrs_keys"] = sorted(attrs0.keys())
            charger = attrs0.get("charging") or attrs0.get("charger") or {}
            history_probe["charger_top_keys"] = (
                sorted(charger.keys()) if isinstance(charger, dict) else None
            )
            trip = attrs0.get("tripstatistics") or {}
            history_probe["tripstatistics_top_keys"] = (
                sorted(trip.keys()) if isinstance(trip, dict) else None
            )
        write_json(OUTPUT_DIR / "06_history_probe.json", history_probe)

        # ---- Step 7: optional rate-limit probe -------------------------
        if rate_limit_probe and vehicles:
            rl = await _rate_limit_probe(vehicles[0])
            write_json(OUTPUT_DIR / "07_rate_limit_probe.json", rl)
        elif rate_limit_probe:
            write_json(
                OUTPUT_DIR / "07_rate_limit_probe.json",
                {"skipped": "no vehicles to probe"},
            )

        # ---- Step 8: optional charging-history endpoint discovery -------
        # The My Cupra app shows per-session charging history but no
        # community library has mapped the endpoint. Try a list of plausible
        # paths derived from the documented API surface and record what
        # comes back. Read-only GETs.
        if history_endpoints_probe and vehicles:
            hep = await _history_endpoint_probe(connection, vehicles[0])
            write_json(OUTPUT_DIR / "08_history_endpoint_probe.json", hep)
        elif history_endpoints_probe:
            write_json(
                OUTPUT_DIR / "08_history_endpoint_probe.json",
                {"skipped": "no vehicles to probe"},
            )

    # ---- Step 8: summary + findings template ---------------------------
    finished_at = datetime.now(timezone.utc)
    summary["finished_at"] = finished_at.isoformat()
    summary["elapsed_seconds"] = round(
        (finished_at - started_at).total_seconds(), 2
    )
    summary["endpoints_attempted"] = len(inventory)
    summary["endpoints_ok"] = sum(1 for r in inventory if r.get("status") == "ok")
    summary["endpoints_errored"] = sum(1 for r in inventory if r.get("status") == "error")
    summary["endpoints_missing"] = sum(1 for r in inventory if r.get("status") == "missing")

    write_json(OUTPUT_DIR / "00_summary.json", summary)
    write_json(OUTPUT_DIR / "05_endpoint_inventory.json", inventory)

    _write_findings_template(summary, inventory)

    print(
        f"[probe] done in {summary['elapsed_seconds']}s — "
        f"{summary['endpoints_ok']} ok, "
        f"{summary['endpoints_errored']} errored, "
        f"{summary['endpoints_missing']} missing"
    )
    print(f"[probe] output in {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    print(f"[probe] findings template at {FINDINGS_PATH.relative_to(REPO_ROOT)}")


def _detect_pycupra_version() -> str:
    try:
        from importlib.metadata import version
        return version("pycupra")
    except Exception:
        try:
            import pycupra  # type: ignore
            return getattr(pycupra, "__version__", "unknown")
        except Exception:
            return "unknown"


# Properties on pycupra's Vehicle (via Dashboard layer) that are most
# relevant to PlugTrack's session-synthesis state machine. Highlighted so
# they appear at the top of the output regardless of dir() ordering.
HIGHLIGHT_PROPERTIES: tuple[str, ...] = (
    # Identity
    "vin", "model", "model_year", "nickname", "primary_drive",
    # Battery / charging — the load-bearing set for v1
    "battery_level", "charging", "charging_state", "charging_power",
    "charge_rate", "charging_time_left", "charging_estimated_end_time",
    "charging_mode", "charging_preferred_mode", "target_soc",
    "charging_cable_connected", "charging_cable_locked",
    "slow_charge", "charging_battery_care", "charging_profile_defined",
    # Wallbox / power-flow signals (useful for state machine)
    "external_power", "energy_flow",
    # Connection health (drives "stale telemetry" detection)
    "vehicle_online", "last_connected", "last_full_update",
    # Range / mileage
    "electric_range", "distance",
    # Position / motion
    "vehicle_moving",
)

# Property names to redact even when not caught by generic redaction
# (e.g. nickname might contain personal text; model_image paths bake in VIN).
REDACT_PROPERTY_NAMES: frozenset[str] = frozenset({
    "nickname", "model_image_large", "model_image_small",
})

# Properties to skip entirely — they duplicate other captures and may bypass
# our redaction (e.g. `json` is a raw string blob of attrs that includes
# unredacted GPS coordinates).
SKIP_PROPERTIES: frozenset[str] = frozenset({"attrs", "json"})


def _capture_vehicle_properties(vehicle: Any) -> dict[str, Any]:
    """Read every public property on the Vehicle and record value + type.

    Resilient to per-property errors: if a property raises (because the
    vehicle's account/hardware doesn't support that telemetry), we record
    the exception rather than aborting. is_*_supported flags are read
    alongside their property to give the practical view.
    """
    out: dict[str, Any] = {
        "highlight": {},
        "all_properties": {},
        "errors": {},
    }

    # Build the universe of names to probe: highlighted names first, then
    # any other public non-callable attribute we discover via introspection.
    seen: set[str] = set()
    name_order: list[str] = []
    for name in HIGHLIGHT_PROPERTIES:
        if name not in seen:
            seen.add(name)
            name_order.append(name)
    for name in dir(vehicle):
        if name.startswith("_") or name in seen or name in SKIP_PROPERTIES:
            continue
        try:
            attr = getattr(type(vehicle), name, None)
        except Exception:
            continue
        # Include @property attributes and basic data attributes; skip methods.
        if callable(getattr(vehicle, name, None)) and not isinstance(attr, property):
            continue
        seen.add(name)
        name_order.append(name)

    for name in name_order:
        try:
            value = getattr(vehicle, name)
        except Exception as exc:
            out["errors"][name] = repr(exc)
            continue
        if callable(value):
            continue  # Skip bound methods that slipped through
        try:
            coerced = to_jsonable(value)
        except Exception as exc:
            out["errors"][name] = f"to_jsonable failed: {exc!r}"
            continue
        if name in REDACT_PROPERTY_NAMES and isinstance(coerced, str):
            coerced = f"<redacted:{len(coerced)}-chars>"
        coerced = redact(coerced, name)

        record = {
            "value": coerced,
            "type": type(value).__name__,
            "is_none": value is None,
        }
        # Pair with is_<name>_supported flag if pycupra exposes one.
        support_attr = f"is_{name}_supported"
        if hasattr(vehicle, support_attr):
            try:
                record["supported"] = bool(getattr(vehicle, support_attr))
            except Exception:
                pass

        if name in HIGHLIGHT_PROPERTIES:
            out["highlight"][name] = record
        else:
            out["all_properties"][name] = record

    out["counts"] = {
        "highlight_captured": len(out["highlight"]),
        "other_captured": len(out["all_properties"]),
        "errored": len(out["errors"]),
    }
    return out


def _name_matches(obj: Any, tokens: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(t in lowered for t in tokens):
            out.append(name)
    return sorted(out)


# Speculative paths to test for the charging-history / charging-statistics
# endpoints. Targets the CARIAD multicharge BFF (host strings extracted from
# the My Cupra Android app via scripts/extract_cupra_endpoints.py).
#
# Two candidate hosts found in the apk:
#   - https://emea.bff.cariad.digital       (general BFF)
#   - https://prod.emea.mobile.charging.cariad.digital   (dedicated charging service)
#
# The path constants (also from the apk) are stored as relative templates:
#   charging_history, charging_history/home, charging_history/public,
#   charging_statistics, charging_statistics/{recordId}/power-curve,
#   charging_sessions
#
# A 200 response on any of these confirms the host+path pairing and gives us
# the JSON shape to map into ChargingSession columns in Phase 3.
# Gentle mode candidates. The bare paths returned 404 on GET against the
# mobile.charging host with bearer accepted (server returned X-Engine: Ktor
# with no auth challenge). The Kotlin request models discovered in the apk
# (ChargingStatisticsRequest(startedAfter=...), HomeChargingHistoryRequest,
# HomeChargingHistoryRequestFilters) suggest POST with JSON body, not GET.
# This iteration tries POST on both candidate hosts.
#
# Each candidate is (method, url, json_body_or_None). 5-second spacing
# between calls; early-exit on 401/403/429 to avoid lockout.
HISTORY_ENDPOINT_CANDIDATES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    # POST on mobile.charging host
    (
        "POST",
        "https://prod.emea.mobile.charging.cariad.digital/charging_statistics",
        {"startedAfter": "2024-01-01T00:00:00Z"},
    ),
    (
        "POST",
        "https://prod.emea.mobile.charging.cariad.digital/charging_history",
        {},
    ),
    (
        "POST",
        "https://prod.emea.mobile.charging.cariad.digital/charging_history/home",
        {},
    ),
    # POST on BFF host
    (
        "POST",
        "https://emea.bff.cariad.digital/charging_statistics",
        {"startedAfter": "2024-01-01T00:00:00Z"},
    ),
    (
        "POST",
        "https://emea.bff.cariad.digital/charging_history",
        {},
    ),
)

HISTORY_ENDPOINT_SPACING_SECONDS: float = 5.0
HISTORY_ENDPOINT_ABORT_STATUSES: frozenset[int] = frozenset({401, 403, 429})


async def _history_endpoint_probe(connection: Any, vehicle: Any) -> dict[str, Any]:
    """Hit a list of plausible charging-history paths and record status.

    Uses aiohttp directly via connection._session, with the authenticated
    headers pycupra has built up post-doLogin. Pycupra's `get(url, vin)`
    raises on non-200 and may eat the status code, so we go one layer below
    to capture the raw response.
    """
    import aiohttp  # type: ignore

    vin = getattr(vehicle, "vin", None) or (getattr(vehicle, "attrs", {}) or {}).get("vin")
    if not vin:
        return {"skipped": "vehicle has no vin"}

    # pycupra carries its session and auth headers internally. Method names
    # vary across versions — fall back through several known attributes.
    session: aiohttp.ClientSession | None = (
        getattr(connection, "_session", None)
        or getattr(connection, "session", None)
    )
    if session is None:
        return {"skipped": "could not locate aiohttp session on Connection"}

    # Pull base URL + auth headers from the connection.
    baseurl = (
        getattr(connection, "_session_base", None)
        or getattr(connection, "_baseurl", None)
        or "https://ola.prod.code.seat.cloud.vwgroup.com"
    )
    user_id = (
        getattr(connection, "_userId", None)
        or getattr(connection, "userId", None)
        or "<missing-user-id>"
    )

    headers = _build_request_headers(connection)

    samples: list[dict[str, Any]] = []
    aborted_reason: str | None = None
    for i, (method, raw_url, body_dict) in enumerate(HISTORY_ENDPOINT_CANDIDATES):
        url = raw_url.replace("{vin}", vin).replace("{userId}", str(user_id))
        rec: dict[str, Any] = {
            "method": method,
            "url": raw_url,
            "request_body": body_dict,
        }
        # Per-call headers: include Content-Type only when sending a body.
        call_headers = dict(headers)
        if method != "GET" and body_dict is not None:
            call_headers["Content-Type"] = "application/json"
        t0 = time.monotonic()
        try:
            request = session.request(
                method,
                url,
                headers=call_headers,
                json=body_dict if method != "GET" else None,
                allow_redirects=False,
            )
            async with request as resp:
                rec["http_status"] = resp.status
                rec["content_type"] = resp.headers.get("Content-Type")
                rec["response_headers"] = {
                    k: v for k, v in resp.headers.items()
                    if k.lower() not in {"set-cookie"}
                }
                body = await resp.read()
                rec["body_bytes"] = len(body)
                # Capture more body for 4xx so error messages survive.
                cap = 2048 if 400 <= rec["http_status"] < 500 else 400
                preview = body[:cap].decode("utf-8", errors="replace")
                rec["body_preview"] = preview
                if rec["http_status"] == 200 and body:
                    try:
                        parsed = json.loads(body)
                        rec["body_schema"] = schema_of(redact(to_jsonable(parsed)))
                    except Exception:
                        pass
                if rec["http_status"] in HISTORY_ENDPOINT_ABORT_STATUSES:
                    aborted_reason = (
                        f"received HTTP {rec['http_status']} on '{method} {raw_url}'; "
                        "halting remaining candidates to avoid lockout."
                    )
                    samples.append(rec)
                    break
        except Exception as exc:
            rec["error"] = repr(exc)
        rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        samples.append(rec)
        if i < len(HISTORY_ENDPOINT_CANDIDATES) - 1:
            await asyncio.sleep(HISTORY_ENDPOINT_SPACING_SECONDS)

    return {
        "purpose": "Probe undocumented Cariad multicharge BFF endpoints (gentle mode).",
        "candidate_count": len(HISTORY_ENDPOINT_CANDIDATES),
        "spacing_seconds": HISTORY_ENDPOINT_SPACING_SECONDS,
        "abort_statuses": sorted(HISTORY_ENDPOINT_ABORT_STATUSES),
        "aborted_early": aborted_reason,
        "headers_sent": _redact_outgoing_headers(headers),
        "two_hundreds": [
            f"{s['method']} {s['url']}" for s in samples if s.get("http_status") == 200
        ],
        "auth_failures": [
            {"method": s["method"], "url": s["url"], "status": s.get("http_status")}
            for s in samples
            if s.get("http_status") in HISTORY_ENDPOINT_ABORT_STATUSES
        ],
        "results": samples,
    }


def _redact_outgoing_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact bearer values in outgoing-header records so the probe output
    can be shared without leaking credentials.
    """
    out = {}
    for k, v in headers.items():
        if k.lower() == "authorization":
            # Preserve scheme + length for diagnostic value.
            scheme, _, rest = v.partition(" ")
            out[k] = f"{scheme} <redacted:{len(rest)}-chars>"
        else:
            out[k] = v
    return out


def _build_request_headers(connection: Any) -> dict[str, str]:
    """Best-effort headers for the Cariad multicharge BFF.

    Header set is informed by APK string-table extraction (X-Brand,
    X-Platform, X-Api-Version, etc.). The bearer token comes from pycupra's
    cached OAuth state; it may be the wrong audience for the BFF, in which
    case the probe will receive 401 and abort. That is itself useful signal.
    """
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Accept-Language": "en-GB",
        "X-Brand": "cupra",
        "X-Platform": "Android",
        # Best-effort User-Agent; the real app builds one at runtime from
        # BuildConfig + okhttp default. Use a recognisable identifier so
        # server-side logs show what hit them.
        "User-Agent": "MyCupra/2.15.0 (com.cupra.mycupra; Android)",
    }
    tokens_dict = (
        getattr(connection, "_session_tokens", None)
        or getattr(connection, "_tokens", None)
        or {}
    )
    access_token = None
    if isinstance(tokens_dict, dict):
        for client_key in ("cupra", "vwg", "default"):
            client_tokens = tokens_dict.get(client_key)
            if isinstance(client_tokens, dict):
                access_token = client_tokens.get("access_token")
                if access_token:
                    break
        if not access_token:
            for v in tokens_dict.values():
                if isinstance(v, dict) and isinstance(v.get("access_token"), str):
                    access_token = v["access_token"]
                    break
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


async def _rate_limit_probe(vehicle: Any) -> dict[str, Any]:
    """Issue a small burst on a cheap endpoint and record latencies + errors.

    Deliberately small (5 calls, 1s spacing) to avoid lockout.
    """
    samples: list[dict[str, Any]] = []
    for i in range(5):
        rec: dict[str, Any] = {"i": i}
        t0 = time.monotonic()
        try:
            await vehicle.get_statusreport()
            rec["status"] = "ok"
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = repr(exc)
        rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        samples.append(rec)
        await asyncio.sleep(1.0)
    return {
        "endpoint_under_test": "Vehicle.get_statusreport",
        "spacing_seconds": 1.0,
        "burst_size": len(samples),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Findings template — pre-populated from probe data so the user only fills
# in narrative prose and confirms the auto-detected values.
# ---------------------------------------------------------------------------

def _write_findings_template(summary: dict[str, Any], inventory: list[dict[str, Any]]) -> None:
    # Once the user has hand-edited the findings doc (Phase 0 deliverable),
    # do not overwrite it. The probe still emits a fresh template alongside
    # under a .auto suffix for diff-comparison if needed.
    if FINDINGS_PATH.exists():
        target = FINDINGS_PATH.with_suffix(".auto.md")
    else:
        target = FINDINGS_PATH
    return _render_findings_template(summary, inventory, target)


def _render_findings_template(summary: dict[str, Any], inventory: list[dict[str, Any]], path: Path) -> None:
    by_status: dict[str, list[str]] = {"ok": [], "error": [], "missing": []}
    for rec in inventory:
        by_status.setdefault(rec.get("status", "?"), []).append(
            f"- `{rec['endpoint']}` — {rec.get('elapsed_ms', '?')}ms"
            + (f" — {rec.get('error', '')}" if rec.get("status") == "error" else "")
        )

    token_path = OUTPUT_DIR / "04_token_inspection.json"
    token_block = ""
    if token_path.exists():
        token = json.loads(token_path.read_text(encoding="utf-8"))
        keys = token.get("token_file_keys") or []
        token_block = "\n".join(f"- `{k}`" for k in keys) or "_no keys captured_"
        for tk, info in (token.get("jwt_inspection") or {}).items():
            ttl = info.get("ttl_seconds")
            exp_iso = info.get("exp_iso")
            token_block += f"\n- **{tk}**: ttl={ttl}s, exp={exp_iso}"

    history_path = OUTPUT_DIR / "06_history_probe.json"
    history_block = "_run probe to populate_"
    if history_path.exists():
        h = json.loads(history_path.read_text(encoding="utf-8"))
        cm = h.get("matches_on_connection") or []
        vm = h.get("matches_on_vehicle") or []
        history_block = (
            f"- Connection-level name matches: {cm or 'none'}\n"
            f"- Vehicle-level name matches: {vm or 'none'}\n"
            f"- Charger top-level keys observed: {h.get('charger_top_keys')}\n"
            f"- Tripstatistics top-level keys observed: {h.get('tripstatistics_top_keys')}"
        )

    md = f"""# pycupra discovery findings

> Auto-generated by `scripts/pycupra_probe.py` on {summary.get('started_at')}.
> This document is gitignored. Review, redact further if needed, and keep
> for Phase 3 reference.

**Run summary**

- pycupra version: `{summary.get('pycupra_version')}`
- Brand: `{summary.get('brand')}`
- Vehicles discovered: {summary.get('vehicle_count', 0)}
- Endpoints attempted: {summary.get('endpoints_attempted')}
- OK / errored / missing: {summary.get('endpoints_ok')} / {summary.get('endpoints_errored')} / {summary.get('endpoints_missing')}
- Total elapsed: {summary.get('elapsed_seconds')}s

---

## 1. Available endpoints and response shapes

Source: `docs/probe_output/05_endpoint_inventory.json` and per-method captures
under `docs/probe_output/03_vehicle_<vinhash>/`.

### Worked

{chr(10).join(by_status['ok']) or '_none_'}

### Errored

{chr(10).join(by_status['error']) or '_none_'}

### Missing on this pycupra version

{chr(10).join(by_status['missing']) or '_none_'}

---

## 2. Field types and example values (redacted)

For each endpoint that returned data, the schema sketch lives under
`docs/probe_output/03_vehicle_<vinhash>/<method>.json` in the `schema` field.
Paste the schema for endpoints we plan to map into Phase 3's
`ChargingSession` / `Car` columns:

- `get_charger` → battery state, target SoC, charging rate, plug status
- `get_statusreport` → odometer (if present), range, doors/locks
- `get_mileage` → total odometer
- `get_position` → GPS, last update timestamp
- `get_basiccardata` → make/model/year/VIN

_Fill in observed shapes here, or copy the relevant schema blocks verbatim._

---

## 3. Pagination behaviour for charging history

**Critical finding (auto-detected):**

{history_block}

If no history endpoint is found on either Connection or Vehicle, document
that here and confirm v1's strategy: PlugTrack persists every observed
`get_charger` snapshot and synthesises sessions from state transitions
(plugged → charging → unplugged), since pycupra surfaces only current state.

_Add commentary on what _did_ work as a charging-history substitute, e.g.
`tripstatistics.dailySums` granularity._

---

## 4. Refresh token TTL observed in practice

Source: `docs/probe_output/04_token_inspection.json`.

Token cache file keys observed:

{token_block}

_Note any difference between `exp - iat` (issued TTL) and observed lifetime
across runs. To measure observed lifetime, re-run the probe a day later;
if `doLogin` succeeds via cached refresh_token, the refresh token is still
valid._

---

## 5. Rate-limit behaviour

Source: `docs/probe_output/07_rate_limit_probe.json` (only if you re-ran with
`PROBE_RATE_LIMIT=1`).

_Run the burst probe once you're confident the basic flow is healthy.
Document: HTTP status codes returned on the Nth call, any 429/Retry-After
headers, observable cooldown duration._

---

## 6. Token cache file format and location

Source: `docs/probe_output/04_token_inspection.json`.

- Path used: `{summary.get('token_file')}`
- File written by: `pycupra.Connection.writeTokenFile`
- File read by: `pycupra.Connection.readTokenFile`
- Format: JSON object, keys listed above
- Production placement (decision for Phase 3): the adapter must point pycupra
  at a path inside the per-container `data/pycupra/` volume so token state
  survives container restarts.

---

## 7. Implications for the v2 schema and adapter

_Fill in once sections 1-6 are confirmed:_

- Which pycupra fields map cleanly to `ChargingSession` columns
- Which fields require synthesis (e.g. session boundaries from charger state)
- Which Cupra-side identifiers are stable enough to use as
  `telematics_session_id` for the unique-on-(car_id, telematics_session_id) index
- Whether `raw_payload` should store `vehicle.attrs.charging` snapshots or
  the synthesised session record
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run())
