# pycupra Telemetry Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface richer pycupra v0.2.32 telemetry in PlugTrack — fill the half-built `charging_mode`, add charge-context fields, persist driving-trip efficiency with a `/driving` page, and display+guard the provider's `requests_remaining` quota.

**Architecture:** All new provider data enters through the single adapter boundary (`plugins/pycupra/adapter.py` → `VehicleState`). New columns reach existing tables via the established `_apply_additive_migrations` hook in `main.py`; the new `CarTripSnapshot` table via `create_all`. Services populate them; the flat JSON API exposes them; React surfaces them on the dashboard, sessions list, session detail, and a new `/driving` page.

**Tech Stack:** FastAPI, async SQLAlchemy, APScheduler, pytest (backend); React 19, Vite, Tailwind 4, zustand, vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-05-30-pycupra-telemetry-enrichment-design.md`

**Conventions (non-negotiable — from CLAUDE.md):**
- Every DB query filters by `user_id`. Distances stored in km with `_km` suffix.
- Cost precedence lives only in `services/cost.py` — do not touch it.
- Tests never touch a real DB (use `test_engine`/`test_sessionmaker` from `conftest.py`).
- Adding to `EXEMPT_PATHS` requires regenerating the security hash + sign-off. **No task here adds an exempt path** (the new route is authed). If a task tries to, stop.
- Settings read via `Settings.get_setting` / the catalogue — never hard-code tunables.

---

## Phase 0 — Probe & Foundation (BLOCKING; everything depends on it)

### Task 0: Probe live pycupra field semantics

Resolve the `[VERIFY]` unknowns in spec §3 before writing coercion logic. This is a manual/investigative task — it changes the plan's assumptions, not the code.

**Files:**
- Run: `scripts/pycupra_probe.py` (existing) and/or `INTEGRATION=1 pytest backend/tests/integration -v`

- [ ] **Step 1: Run the probe** (requires `.env.probe`, local only)

```bash
cd backend && INTEGRATION=1 python ../scripts/pycupra_probe.py
```

- [ ] **Step 2: Record the observed shape** for each field into a scratch note (paste into the implementing PR description). Confirm:
  - `charge_rate` — numeric? unit (%/h vs km/h)?
  - `charge_max_ampere` — int amps, or enum string (`"maximum"`/`"reduced"`/`"5"`/...)?
  - `charging_mode` and `charging_preferred_mode` — exact string values.
  - `charging_estimated_end_time` — ISO string, epoch, or datetime?
  - `requests_remaining` — int, or nested dict (e.g. `{"remaining": N}`)?
  - `trip_last_entry` / `trip_last_cycle_entry` — dict keys; pick a stable dedup key (id or `tripEndTimestamp`/`timestamp`). If none stable, fall back to `captured_at` rounded to the minute.
  - `charging_battery_care` vs `slow_charge` — which reflects "reduced charge speed"?

- [ ] **Step 3: Update spec §3 / §4 assumptions** inline if reality differs (e.g. if `charge_max_ampere` is an enum, set the spec's decision: store raw string in `raw_payload`, leave `max_charge_current_a` null). Commit the spec edit.

```bash
git add docs/superpowers/specs/2026-05-30-pycupra-telemetry-enrichment-design.md
git commit -m "docs(spec): lock pycupra field semantics from live probe"
```

> If the probe cannot run (no `.env.probe`), proceed with the spec's stated assumptions but mark every coercion with a `# [VERIFY]` comment and add a unit test asserting graceful `None` fallback for unexpected shapes.

---

### Task 1: `TripSnapshot` dataclass + `VehicleState` fields

**Files:**
- Modify: `backend/plugtrack/plugins/pycupra/models.py`
- Test: `backend/tests/test_pycupra_adapter.py`

- [ ] **Step 1: Write the failing test** (append to `test_pycupra_adapter.py`)

```python
from plugtrack.plugins.pycupra.models import TripSnapshot, VehicleState


def test_vehiclestate_has_enrichment_fields_defaulting_none():
    vs = VehicleState(
        battery_level=50, charging=False, charging_state=False,
        charging_state_raw="", charging_power=None, charging_time_left=None,
        target_soc=None, charging_cable_connected=False,
        charging_cable_locked=None, external_power=None, energy_flow=None,
        vehicle_online=True, last_connected=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc),
        distance_km=None, electric_range_km=None, position=None,
        car_captured_timestamp=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc),
    )
    assert vs.charging_mode_raw is None
    assert vs.charge_rate is None
    assert vs.max_charge_current is None
    assert vs.battery_care is None
    assert vs.min_charge_level is None
    assert vs.charging_estimated_end_at is None
    assert vs.requests_remaining is None
    assert vs.trip_last is None
    assert vs.trip_last_cycle is None


def test_tripsnapshot_is_frozen():
    import datetime as dt
    t = TripSnapshot(
        kind="last", entry_key="abc",
        captured_at=dt.datetime.now(dt.timezone.utc),
        avg_consumption_kwh_per_100km=18.2, total_consumption_kwh=4.1,
        length_km=22.0, duration_min=31, avg_speed_kmh=42.0,
        avg_recuperation_kwh_per_100km=2.1,
    )
    import pytest
    with pytest.raises(Exception):
        t.kind = "cycle"  # frozen
```

- [ ] **Step 2: Run it, expect failure**

Run: `pytest backend/tests/test_pycupra_adapter.py -k enrichment_fields -v`
Expected: FAIL (`TripSnapshot` undefined / new fields missing).

- [ ] **Step 3: Implement** — add to `models.py`

```python
@dataclass(frozen=True)
class TripSnapshot:
    """A single car-reported trip's efficiency figures.

    `kind` distinguishes a single drive (`"last"`) from the since-reset /
    long-term cycle (`"cycle"`). `entry_key` is a stable dedup key derived
    from pycupra's trip entry (see spec §3); falls back to the captured
    timestamp rounded to the minute when no stable id exists.
    """

    kind: str
    entry_key: str
    captured_at: datetime
    avg_consumption_kwh_per_100km: Optional[float]
    total_consumption_kwh: Optional[float]
    length_km: Optional[float]
    duration_min: Optional[int]
    avg_speed_kmh: Optional[float]
    avg_recuperation_kwh_per_100km: Optional[float]
```

Then extend `VehicleState` with the new optional fields (all default `None`), appended **after** `car_captured_timestamp` so existing positional constructors in tests stay valid only if keyword — confirm existing call sites use keywords (they do in `adapter.py`). Add:

```python
    charging_mode_raw: Optional[str] = None
    charge_rate: Optional[float] = None
    max_charge_current: Optional[float] = None
    battery_care: Optional[bool] = None
    min_charge_level: Optional[int] = None
    charging_estimated_end_at: Optional[datetime] = None
    requests_remaining: Optional[int] = None
    trip_last: Optional["TripSnapshot"] = None
    trip_last_cycle: Optional["TripSnapshot"] = None
```

> `VehicleState` is `@dataclass(frozen=True)`; all current fields are required (no defaults). Adding defaulted fields at the end is valid. Place `TripSnapshot` **above** `VehicleState` so the annotation resolves.

- [ ] **Step 4: Run, expect pass**

Run: `pytest backend/tests/test_pycupra_adapter.py -k "enrichment_fields or tripsnapshot" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/plugins/pycupra/models.py backend/tests/test_pycupra_adapter.py
git commit -m "feat(pycupra): add TripSnapshot + enrichment fields to VehicleState"
```

---

### Task 2: Adapter reads enrichment fields + trips + mode normaliser

**Files:**
- Modify: `backend/plugtrack/plugins/pycupra/adapter.py`
- Test: `backend/tests/test_pycupra_adapter.py`

- [ ] **Step 1: Write failing tests** — use a fake Vehicle object exposing properties + `is_*_supported` flags. Follow the existing `_safe_attr` contract (a property whose `is_<name>_supported` is `False` returns the default).

```python
class _FakeVehicle:
    def __init__(self, **attrs):
        self._a = attrs
    def __getattr__(self, name):
        if name in self._a:
            return self._a[name]
        if name.startswith("is_") and name.endswith("_supported"):
            base = name[3:-10]
            return base in self._a
        raise AttributeError(name)


def test_normalise_charging_mode_maps_known_values():
    from plugtrack.plugins.pycupra.adapter import _normalise_charging_mode
    assert _normalise_charging_mode("manual") == "manual"
    assert _normalise_charging_mode("timer") == "timer"
    assert _normalise_charging_mode("profile") == "profile"
    assert _normalise_charging_mode("invalidValue") == "unknown"
    assert _normalise_charging_mode(None) == "unknown"


def test_read_trip_builds_snapshot_or_none():
    from plugtrack.plugins.pycupra.adapter import _read_trip
    v = _FakeVehicle(
        trip_last_average_electric_consumption=18.5,
        trip_last_total_electric_consumption=4.0,
        trip_last_length=21.0,
        trip_last_duration=30,
        trip_last_average_speed=42.0,
        trip_last_average_recuperation=2.0,
        trip_last_entry={"tripID": "T-123"},
    )
    snap = _read_trip(v, "last")
    assert snap is not None
    assert snap.kind == "last"
    assert snap.entry_key == "T-123"
    assert snap.avg_consumption_kwh_per_100km == 18.5
    # Unsupported car → None
    assert _read_trip(_FakeVehicle(), "last") is None
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest backend/tests/test_pycupra_adapter.py -k "normalise_charging_mode or read_trip" -v`
Expected: FAIL (functions undefined).

- [ ] **Step 3: Implement** in `adapter.py`. Add the normaliser and the trip reader, and read the new fields in `fetch_vehicle_state`'s `VehicleState(...)` construction. **Adjust property names / dedup key per Task 0 findings.**

```python
_CHARGING_MODE_VALUES = {"manual", "timer", "profile"}


def _normalise_charging_mode(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip().lower() in _CHARGING_MODE_VALUES:
        return raw.strip().lower()
    return "unknown"


def _read_trip(vehicle: Any, kind: str) -> Optional["TripSnapshot"]:
    prefix = "trip_last" if kind == "last" else "trip_last_cycle"
    avg = _coerce_float(_safe_attr(vehicle, f"{prefix}_average_electric_consumption"))
    total = _coerce_float(_safe_attr(vehicle, f"{prefix}_total_electric_consumption"))
    length = _coerce_float(_safe_attr(vehicle, f"{prefix}_length"))
    duration = _coerce_int(_safe_attr(vehicle, f"{prefix}_duration"))
    speed = _coerce_float(_safe_attr(vehicle, f"{prefix}_average_speed"))
    recup = _coerce_float(_safe_attr(vehicle, f"{prefix}_average_recuperation"))
    # If the car reports nothing useful, skip.
    if all(v is None for v in (avg, total, length, duration, speed, recup)):
        return None
    entry = _safe_attr(vehicle, f"{prefix}_entry")
    entry_key = _trip_entry_key(entry)
    return TripSnapshot(
        kind=kind, entry_key=entry_key, captured_at=_utcnow(),
        avg_consumption_kwh_per_100km=avg, total_consumption_kwh=total,
        length_km=length, duration_min=duration, avg_speed_kmh=speed,
        avg_recuperation_kwh_per_100km=recup,
    )


def _trip_entry_key(entry: Any) -> str:
    # Prefer a stable id; fall back to a timestamp; finally to "now" minute.
    if isinstance(entry, dict):
        for k in ("tripID", "id", "tripEndTimestamp", "timestamp", "carCapturedTimestamp"):
            if entry.get(k):
                return str(entry[k])
    return _utcnow().strftime("%Y-%m-%dT%H:%M")
```

Import `TripSnapshot` from `.models`. In `fetch_vehicle_state`, add to the `VehicleState(...)` kwargs:

```python
        charging_mode_raw=_safe_attr(vehicle, "charging_mode")
            or _safe_attr(vehicle, "charging_preferred_mode"),
        charge_rate=_coerce_float(_safe_attr(vehicle, "charge_rate")),
        max_charge_current=_coerce_float(_safe_attr(vehicle, "charge_max_ampere")),
        battery_care=_coerce_optional_bool(_safe_attr(vehicle, "charging_battery_care")),
        min_charge_level=_coerce_int(_safe_attr(vehicle, "min_charge_level")),
        charging_estimated_end_at=_coerce_optional_datetime(
            _safe_attr(vehicle, "charging_estimated_end_time")),
        requests_remaining=_coerce_int(_safe_attr(vehicle, "requests_remaining")),
        trip_last=_read_trip(vehicle, "last"),
        trip_last_cycle=_read_trip(vehicle, "cycle"),
```

Add `_coerce_optional_datetime` (returns `None` instead of `_utcnow()` for missing/bad input — unlike the existing `_coerce_datetime`):

```python
def _coerce_optional_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            from datetime import datetime as _dt
            parsed = _dt.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None
```

> If Task 0 shows `charge_max_ampere` is an enum string, replace its line with `max_charge_current=None` and stash the raw string into the session `raw_payload` later (Task 7). Note it in a `# [VERIFY]` comment.

- [ ] **Step 4: Run, expect pass**

Run: `pytest backend/tests/test_pycupra_adapter.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/plugins/pycupra/adapter.py backend/tests/test_pycupra_adapter.py
git commit -m "feat(pycupra): adapter reads charge-context + trip fields"
```

---

## Phase 1 — Persistence (depends on Phase 0)

### Task 3: `CarTripSnapshot` model

**Files:**
- Create: `backend/plugtrack/models/car_trip_snapshot.py`
- Modify: `backend/plugtrack/models/__init__.py` (export it)
- Test: `backend/tests/test_models_smoke.py` (or create `backend/tests/test_car_trip_snapshot.py`)

- [ ] **Step 1: Write the failing test**

```python
import datetime as dt
import pytest
from sqlalchemy import select
from plugtrack.models import CarTripSnapshot


@pytest.mark.asyncio
async def test_trip_snapshot_unique_on_car_kind_entry(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(CarTripSnapshot(
            user_id=user_id, car_id=car_id, kind="last", entry_key="T-1",
            captured_at=dt.datetime.now(dt.timezone.utc),
            avg_consumption_kwh_per_100km=18.0, total_consumption_kwh=3.0,
            length_km=16.6, duration_min=25, avg_speed_kmh=40.0,
            avg_recuperation_kwh_per_100km=1.5))
        await s.commit()
    # Same (car, kind, entry) must violate the unique index.
    async with test_sessionmaker() as s:
        s.add(CarTripSnapshot(
            user_id=user_id, car_id=car_id, kind="last", entry_key="T-1",
            captured_at=dt.datetime.now(dt.timezone.utc),
            avg_consumption_kwh_per_100km=99.0, total_consumption_kwh=9.0,
            length_km=1.0, duration_min=1, avg_speed_kmh=1.0,
            avg_recuperation_kwh_per_100km=0.0))
        with pytest.raises(Exception):
            await s.commit()
```

> If no `seeded_user_car` fixture exists, add one to `conftest.py` that inserts a `User` + `Car` and returns `(user_id, car_id)`, following the existing fixture style. Check `conftest.py` first and reuse any existing helper.

- [ ] **Step 2: Run, expect failure**

Run: `pytest backend/tests/test_car_trip_snapshot.py -v`
Expected: FAIL (`CarTripSnapshot` undefined).

- [ ] **Step 3: Implement** `car_trip_snapshot.py` (mirror the style of `charging_session.py`)

```python
"""Car-reported trip efficiency snapshot — driving-side complement to
charging sessions. One row per distinct trip the car reports.

`kind` is "last" (single drive) or "cycle" (since-reset / long-term).
The partial unique index on (car_id, kind, entry_key) makes re-polling
the same trip idempotent — mirrors the ChargingSession telematics index.
Distances stored in km (`length_km`) per the distance-storage rule.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CarTripSnapshot(Base):
    __tablename__ = "car_trip_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    car_id: Mapped[int] = mapped_column(ForeignKey("car.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # last | cycle
    entry_key: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    avg_consumption_kwh_per_100km: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    total_consumption_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    length_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_recuperation_kwh_per_100km: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_trip_car_kind_entry",
            "car_id", "kind", "entry_key",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CarTripSnapshot id={self.id} car={self.car_id} "
            f"{self.kind} {self.entry_key}>"
        )
```

Add `from .car_trip_snapshot import CarTripSnapshot` to `models/__init__.py` and include in `__all__`.

- [ ] **Step 4: Run, expect pass**

Run: `pytest backend/tests/test_car_trip_snapshot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/models/car_trip_snapshot.py backend/plugtrack/models/__init__.py backend/tests/test_car_trip_snapshot.py
git commit -m "feat(models): add CarTripSnapshot table"
```

---

### Task 4: Additive columns on `ChargingSession` + `CarStateSnapshot`

**Files:**
- Modify: `backend/plugtrack/models/charging_session.py`, `backend/plugtrack/models/car_state.py`
- Modify: `backend/plugtrack/main.py` (`_apply_additive_migrations`)
- Test: `backend/tests/test_additive_migrations.py` (create) + extend a models test

- [ ] **Step 1: Write the failing test** — assert the new columns exist on a fresh metadata create (the test DB uses `create_all`, which builds the columns from the model; the migration list is for *existing* prod DBs).

```python
import datetime as dt
import pytest
from plugtrack.models import ChargingSession, CarStateSnapshot


@pytest.mark.asyncio
async def test_session_has_context_columns(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = ChargingSession(
            user_id=user_id, car_id=car_id, date=dt.date.today(),
            start_soc=20, end_soc=80, kwh_added=10.0, source="synthesis",
            charging_mode="timer", battery_care=True, max_charge_current_a=16.0)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.battery_care is True
        assert row.max_charge_current_a == 16.0


@pytest.mark.asyncio
async def test_car_state_has_live_context_columns(test_sessionmaker, seeded_user_car):
    _user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = CarStateSnapshot(
            car_id=car_id, last_charge_rate=12.0, last_battery_care=True,
            last_min_charge_level=20, last_max_charge_current_a=16.0,
            last_requests_remaining=5,
            last_charging_estimated_end_at=dt.datetime.now(dt.timezone.utc))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.last_requests_remaining == 5
```

- [ ] **Step 2: Run, expect failure** — `pytest backend/tests/test_additive_migrations.py -v` → FAIL (unknown columns).

- [ ] **Step 3: Implement**

In `charging_session.py`, after `charging_mode`, add:

```python
    battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    max_charge_current_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
```

In `car_state.py`, after `last_charging_power_kw`, add:

```python
    last_charge_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_charging_estimated_end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_min_charge_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_max_charge_current_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    last_requests_remaining: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
```

Add `Boolean` to the `car_state.py` sqlalchemy import line.

In `main.py` `_apply_additive_migrations`, extend the `additions` tuple (these run on existing prod SQLite DBs):

```python
    additions = (
        ("location", "default_charge_network", "VARCHAR(64)"),
        ("charging_session", "battery_care", "BOOLEAN"),
        ("charging_session", "max_charge_current_a", "FLOAT"),
        ("car_state", "last_charge_rate", "FLOAT"),
        ("car_state", "last_charging_estimated_end_at", "DATETIME"),
        ("car_state", "last_battery_care", "BOOLEAN"),
        ("car_state", "last_min_charge_level", "INTEGER"),
        ("car_state", "last_max_charge_current_a", "FLOAT"),
        ("car_state", "last_requests_remaining", "INTEGER"),
    )
```

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_additive_migrations.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/models/charging_session.py backend/plugtrack/models/car_state.py backend/plugtrack/main.py backend/tests/test_additive_migrations.py
git commit -m "feat(models): charge-context + live-context columns w/ additive migration"
```

---

## Phase 2 — Settings (independent; can run parallel with Phase 1)

### Task 5: New catalogue settings

**Files:**
- Modify: `backend/plugtrack/settings/catalogue.py`
- Test: `backend/tests/api/test_settings.py` (extend) or `backend/tests/test_settings_catalogue.py`

- [ ] **Step 1: Write the failing test**

```python
def test_new_enrichment_settings_present():
    from plugtrack.settings.catalogue import CATALOGUE  # confirm export name
    keys = {e.key for e in CATALOGUE}
    assert "force_refresh_min_remaining_requests" in keys
    assert "driving_efficiency_window_days" in keys
```

> Confirm the catalogue's exported name (grep `catalogue.py` for the module-level list). Adjust the import if it differs.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — add two `CatalogueEntry` items (match existing field names exactly):

```python
    CatalogueEntry(
        key="force_refresh_min_remaining_requests",
        value_type="int",
        group_name="sync",
        label="Min remote requests to keep in reserve",
        description="Skip force-refresh when the provider reports this many or "
                    "fewer remote requests remaining, to avoid lockout.",
        default_value="2",
    ),
    CatalogueEntry(
        key="driving_efficiency_window_days",
        value_type="int",
        group_name="display",
        label="Driving-efficiency rolling window (days)",
        description="Window for the dashboard's rolling average driving efficiency.",
        default_value="30",
    ),
```

> Use whatever `value_type` the catalogue supports for integers (`"int"` or `"float"`). If only `float` exists, use it and coerce on read.

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/settings/catalogue.py backend/tests/test_settings_catalogue.py
git commit -m "feat(settings): add force-refresh reserve + efficiency window keys"
```

---

## Phase 3 — Services (depends on Phases 0–2)

### Task 6: Synthesiser populates `charging_mode` (+ context passthrough)

**Files:**
- Modify: `backend/plugtrack/services/session_synthesiser.py`
- Test: `backend/tests/test_session_synthesiser.py`

- [ ] **Step 1: Write the failing test** — feed a telemetry sample whose `charging_mode_raw="timer"` and assert the emitted open-session payload carries `charging_mode == "timer"`, `battery_care`, `max_charge_current`.

```python
def test_open_session_payload_carries_charging_mode_and_context():
    # Build the synthesiser's telemetry input with the new fields set.
    # (Mirror the existing test's sample construction; set:
    #   charging_mode_raw="timer", battery_care=True, max_charge_current=16.0)
    # Drive the state machine plug-in -> charging, capture the open payload,
    # then assert:
    assert open_payload["charging_mode"] == "timer"
    assert open_payload["battery_care"] is True
    assert open_payload["max_charge_current"] == 16.0
```

> Read `test_session_synthesiser.py` first to reuse its sample/telemetry builder and the exact way it captures emitted payloads. The synthesiser is a pure state machine — no DB.

- [ ] **Step 2: Run, expect failure** (payload still has `"unknown"` / missing keys).

- [ ] **Step 3: Implement** — at the four payload dicts (lines ~163–216), replace `"charging_mode": "unknown"` with the normalised telemetry value and add the two context keys. The synthesiser already imports/reads `telemetry`; the raw mode normalisation happens in the adapter, so `telemetry.charging_mode_raw` is already `"timer"`-style — but normalise defensively:

```python
                "charging_mode": telemetry.charging_mode_raw or "unknown",
                "battery_care": telemetry.battery_care,
                "max_charge_current": telemetry.max_charge_current,
```

> If the adapter does NOT pre-normalise (it stores raw), import and apply `_normalise_charging_mode` here instead. Keep one normalisation point — prefer the adapter's. Confirm which by checking Task 2's output.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_session_synthesiser.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/session_synthesiser.py backend/tests/test_session_synthesiser.py
git commit -m "feat(sessions): populate charging_mode + context from telemetry"
```

---

### Task 7: Worker persists session context + captures trips

**Files:**
- Modify: `backend/plugtrack/services/sync_worker.py`
- Test: `backend/tests/test_sync_worker.py`

- [ ] **Step 1: Write failing tests**

(a) `_handle_open_session` writes `battery_care` + `max_charge_current_a` onto the `ChargingSession` (mode already covered by passthrough). Assert via the DB row.

(b) A new `_capture_trips(car, telemetry)` inserts `CarTripSnapshot` rows and is idempotent: calling it twice with the same `entry_key` leaves exactly one row per `(kind, entry_key)`.

```python
@pytest.mark.asyncio
async def test_capture_trips_is_idempotent(worker, seeded_user_car, make_telemetry):
    user_id, car_id = seeded_user_car
    tel = make_telemetry(
        trip_last=TripSnapshot(kind="last", entry_key="T-9", ...),
        trip_last_cycle=None)
    await worker._capture_trips(car, tel)
    await worker._capture_trips(car, tel)  # second call: no dup
    async with worker._db_sessionmaker() as s:
        rows = (await s.execute(select(CarTripSnapshot).where(
            CarTripSnapshot.car_id == car_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].entry_key == "T-9"
```

> Reuse the worker fixtures already in `test_sync_worker.py` (it constructs a worker with `test_sessionmaker`). Read that file for the `make_telemetry`/`VehicleState` builder and the `car` fixture shape.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

In `_handle_open_session` (around line 513), add the new columns to the `ChargingSession(...)` constructor:

```python
                battery_care=payload.get("battery_care"),
                max_charge_current_a=payload.get("max_charge_current"),
```

And stash `min_charge_level` / any raw enum into `raw_payload`:

```python
                raw_payload={
                    "charging_state_raw": telemetry.charging_state_raw,
                    "charging_power": telemetry.charging_power,
                    "target_soc": telemetry.target_soc,
                    "min_charge_level": telemetry.min_charge_level,
                },
```

Add the `_capture_trips` method (idempotent upsert via SQLite `INSERT OR IGNORE` / `on_conflict_do_nothing`):

```python
    async def _capture_trips(self, car: Car, telemetry: VehicleState) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from ..models import CarTripSnapshot

        snaps = [t for t in (telemetry.trip_last, telemetry.trip_last_cycle)
                 if t is not None]
        if not snaps:
            return
        async with self._db_sessionmaker() as session:
            for t in snaps:
                stmt = sqlite_insert(CarTripSnapshot).values(
                    user_id=car.user_id, car_id=car.id, kind=t.kind,
                    entry_key=t.entry_key, captured_at=t.captured_at,
                    avg_consumption_kwh_per_100km=t.avg_consumption_kwh_per_100km,
                    total_consumption_kwh=t.total_consumption_kwh,
                    length_km=t.length_km, duration_min=t.duration_min,
                    avg_speed_kmh=t.avg_speed_kmh,
                    avg_recuperation_kwh_per_100km=t.avg_recuperation_kwh_per_100km,
                ).on_conflict_do_nothing(
                    index_elements=["car_id", "kind", "entry_key"])
                await session.execute(stmt)
            await session.commit()
```

Call `_capture_trips` once per successful sync — locate where the worker finishes processing telemetry for a car (after state-machine handling, before returning) and add `await self._capture_trips(car, telemetry)`. Also persist the new `CarStateSnapshot` live fields wherever it currently upserts `car_state` (grep `CarStateSnapshot` in the worker): set `last_charge_rate`, `last_charging_estimated_end_at`, `last_battery_care`, `last_min_charge_level`, `last_max_charge_current_a`, `last_requests_remaining` from telemetry.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_sync_worker.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/sync_worker.py backend/tests/test_sync_worker.py
git commit -m "feat(sync): persist session context + capture trip snapshots"
```

---

### Task 8: Orchestrator caches quota + guards force_refresh

**Files:**
- Modify: `backend/plugtrack/services/sync_orchestrator.py`
- Test: `backend/tests/test_sync_orchestrator.py` (create if absent) or `test_sync_worker.py`

- [ ] **Step 1: Write failing test** — with `requests_remaining=1` cached and reserve=2, `force_refresh` must NOT call the adapter's `setRefresh`, and should emit/record a skip reason.

```python
@pytest.mark.asyncio
async def test_force_refresh_skipped_when_quota_low(orchestrator, fake_adapter):
    orchestrator.update_live_quota(car_id=1, requests_remaining=1)
    result = await orchestrator.force_refresh(car_id=1, min_remaining=2)
    assert result.skipped is True
    assert result.reason == "low_quota"
    assert fake_adapter.set_refresh_calls == 0
```

> Read `sync_orchestrator.py` fully first. The existing `force_refresh` path (and the 30-min cap) live there; match its actual signature and return type. If `force_refresh` returns a `SyncJob`, add a guarded early-return that emits `sync.refresh_skipped` via the event bus and returns a completed/failed job with the reason rather than inventing a new type.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — add `last_requests_remaining: Optional[int] = None` to `CarSyncState`; a setter that the worker/orchestrator updates each sync; and the guard in `force_refresh`. Read the reserve threshold from settings (`force_refresh_min_remaining_requests`) at the call site (the route/scheduler that invokes force refresh passes it, or the orchestrator reads it via the same settings accessor the worker uses).

```python
        st = self._state.get(car_id)
        if (st is not None and st.last_requests_remaining is not None
                and st.last_requests_remaining <= min_remaining):
            await self._event_bus.publish(Event(
                job_id=..., type="sync.refresh_skipped",
                data={"car_id": car_id, "reason": "low_quota",
                      "requests_remaining": st.last_requests_remaining}))
            # return the same shape force_refresh normally returns
```

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "feat(sync): guard force_refresh against low provider quota"
```

---

### Task 9: Dashboard service — live context + driving-efficiency aggregate

**Files:**
- Modify: `backend/plugtrack/services/dashboard_service.py`
- Test: `backend/tests/test_dashboard_service.py`

- [ ] **Step 1: Write failing tests** — (a) `CarPanel` carries the new live fields from orchestrator state; (b) a `DrivingEfficiency` aggregate is computed from `CarTripSnapshot` `last`-kind rows within the window (latest + rolling avg + sample_count).

```python
@pytest.mark.asyncio
async def test_dashboard_includes_driving_efficiency(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        for ek, avg in (("T-1", 16.0), ("T-2", 20.0)):
            s.add(CarTripSnapshot(
                user_id=user_id, car_id=car_id, kind="last", entry_key=ek,
                captured_at=dt.datetime.now(dt.timezone.utc),
                avg_consumption_kwh_per_100km=avg, total_consumption_kwh=None,
                length_km=None, duration_min=None, avg_speed_kmh=None,
                avg_recuperation_kwh_per_100km=None))
        await s.commit()
        summary = await dashboard_summary(s, user_id=user_id, orchestrator=None)
    panel = summary.cars[0]
    assert panel.driving_efficiency is not None
    assert panel.driving_efficiency.sample_count == 2
    assert panel.driving_efficiency.latest_kwh_per_100km == 20.0  # most recent
    assert round(panel.driving_efficiency.rolling_avg_kwh_per_100km, 1) == 18.0
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — add a `DrivingEfficiency` dataclass and `driving_efficiency: Optional[DrivingEfficiency] = None` to `CarPanel`. In the per-car loop, pull the new live fields from `live` (orchestrator state) via `getattr(live, "last_charge_rate", None)` etc., and add them to the `CarPanel(...)` construction. After the loop body (or inline), query `CarTripSnapshot` for the car (kind="last", within window days, ordered by `captured_at` desc), compute latest + mean + count.

```python
@dataclass
class DrivingEfficiency:
    latest_kwh_per_100km: Optional[float]
    rolling_avg_kwh_per_100km: Optional[float]
    sample_count: int
```

Add new optional fields to `CarPanel`: `charge_rate`, `charging_estimated_end_at`, `battery_care`, `min_charge_level`, `max_charge_current_a`, `requests_remaining` (all default `None`). Window days via settings (`driving_efficiency_window_days`); the dashboard route already has a session — read the setting through the existing settings accessor used elsewhere in the service layer.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_dashboard_service.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/dashboard_service.py backend/tests/test_dashboard_service.py
git commit -m "feat(dashboard): live charge-context + driving-efficiency aggregate"
```

---

## Phase 4 — API (depends on Phase 3)

### Task 10: Session payload + trips endpoint

**Files:**
- Modify: `backend/plugtrack/api/routes/sessions.py` (payload + update model)
- Modify/Create: `backend/plugtrack/api/routes/cars.py` (or a new `trips.py`) for `GET /api/cars/{id}/trips`
- Modify: `backend/plugtrack/main.py` (register the route if new module)
- Test: `backend/tests/api/test_sessions.py`, `backend/tests/api/test_trips.py` (create)

- [ ] **Step 1: Write failing tests**

(a) `GET /api/sessions/{id}` response includes `battery_care` + `max_charge_current_a`; `PUT` accepts them.
(b) `GET /api/cars/{id}/trips` returns the user's trips for that car, newest first, and **404/empty for another user's car** (isolation).

```python
@pytest.mark.asyncio
async def test_trips_endpoint_isolates_by_user(client, other_users_car_with_trips):
    resp = await client.get(f"/api/cars/{other_users_car_with_trips}/trips")
    assert resp.status_code in (403, 404)
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

In `sessions.py`: add `battery_care: Optional[bool]` and `max_charge_current_a: Optional[float]` to the `ChargingSessionPayload` response model and the serialiser (around line 192), and to `SessionUpdateRequest` + the update handler (around line 367). Follow the existing field-by-field mapping exactly.

New endpoint (in `cars.py`, reuse its router + auth dependency):

```python
@router.get("/cars/{car_id}/trips")
async def list_car_trips(
    car_id: int, request: Request, kind: str | None = None, limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    car = await session.get(Car, car_id)
    if car is None or car.user_id != user_id:
        raise HTTPException(status_code=404, detail="Car not found")
    stmt = (select(CarTripSnapshot)
            .where(CarTripSnapshot.user_id == user_id,
                   CarTripSnapshot.car_id == car_id))
    if kind in ("last", "cycle"):
        stmt = stmt.where(CarTripSnapshot.kind == kind)
    stmt = stmt.order_by(CarTripSnapshot.captured_at.desc()).limit(min(limit, 200))
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "kind": r.kind, "captured_at": r.captured_at,
         "avg_consumption_kwh_per_100km": r.avg_consumption_kwh_per_100km,
         "total_consumption_kwh": r.total_consumption_kwh,
         "length_km": r.length_km, "duration_min": r.duration_min,
         "avg_speed_kmh": r.avg_speed_kmh,
         "avg_recuperation_kwh_per_100km": r.avg_recuperation_kwh_per_100km}
        for r in rows
    ]
```

> Match `cars.py`'s actual router prefix/auth pattern. Do **not** add to `EXEMPT_PATHS`. If `cars.py` already prefixes `/cars`, register the path accordingly so the final URL is `/api/cars/{id}/trips`.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/api -v`. Then **`pytest backend/tests/api/test_security_invariants.py -v` must still pass** (no exempt-path change).

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/api/routes/ backend/plugtrack/main.py backend/tests/api/
git commit -m "feat(api): session context fields + car trips endpoint"
```

---

### Task 11: Dashboard + sync status payload fields

**Files:**
- Modify: `backend/plugtrack/api/routes/` dashboard route (serialises `DashboardSummary`) + sync status route
- Test: `backend/tests/api/test_dashboard.py`, `backend/tests/api/test_sync*.py`

- [ ] **Step 1: Write failing test** — `GET /api/dashboard` car panel JSON includes `driving_efficiency`, `charge_rate`, `battery_care`, `requests_remaining` etc.; sync status JSON includes `requests_remaining`.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — `DashboardSummary.to_dict()` uses `asdict`, so the new `CarPanel`/`DrivingEfficiency` fields serialise automatically; just confirm the dashboard route returns `to_dict()` unchanged and add a test. For sync status, add `requests_remaining` to the status serialiser (grep the sync route for where `CarSyncState` is serialised — there's an existing `next_poll_at`/`active_job_id` dict around `sync_orchestrator.py:148`).

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/api/ backend/tests/api/
git commit -m "feat(api): expose driving efficiency + quota in dashboard/sync"
```

---

## Phase 5 — Frontend (depends on Phase 4)

> Run `npm run typecheck` (`tsc -b` is stricter — see memory) **and** `npm test` after each task. Distances via `formatDistance`/`kmToMi`; honour `distance_unit`.

### Task 12: API client types

**Files:**
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts` (if present) or rely on `typecheck`

- [ ] **Step 1:** Add fields to `DashboardCarPanel` (`charge_rate`, `charging_estimated_end_at`, `battery_care`, `min_charge_level`, `max_charge_current_a`, `requests_remaining`, `driving_efficiency: { latest_kwh_per_100km, rolling_avg_kwh_per_100km, sample_count } | null`), to `ChargingSessionPayload` + `SessionUpdateRequest` (`battery_care`, `max_charge_current_a`), and a new `CarTripPayload` type + `api.getCarTrips(carId, kind?)` method following the existing client method pattern.
- [ ] **Step 2:** `npm run typecheck` — expect failures in consumers (next tasks fix them) or clean if additive-optional.
- [ ] **Step 3:** Commit.

```bash
git add frontend/src/api/client.ts && git commit -m "feat(ui): client types for telemetry enrichment"
```

### Task 13: SessionDetail — Charge context section + edit inputs

**Files:**
- Modify: `frontend/src/pages/SessionDetail.tsx`
- Test: `frontend/src/pages/SessionDetail.test.tsx`

- [ ] **Step 1: Write failing test** — render a session with `charging_mode="timer"`, `charging_type="ac"`, `battery_care=true`, `max_charge_current_a=16` and assert a "Charge context" section shows "Timer", "AC", "Battery care", "16 A".
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** — add a `ChargeContext` section (mirror `ChargeMechanics` structure with `StatTile`s), suppressed when all four are null/unknown. Add `battery_care` + `max_charge_current_a` inputs to `SessionEditForm` and include them in the `SessionUpdateRequest` body.
- [ ] **Step 4: Run, expect pass** (`npm test -- SessionDetail`).
- [ ] **Step 5: Commit.**

### Task 14: Sessions list — mode/type hint

**Files:**
- Modify: `frontend/src/pages/Sessions.tsx`
- Test: `frontend/src/pages/Sessions.test.tsx`

- [ ] **Step 1: Write failing test** — a synthesis row with `charging_mode="timer"`, `charging_type="dc"` renders a `Timer · DC` hint in the subtext line.
- [ ] **Step 2–4:** Implement in `SessionRow` (append to the existing `kWh @ tariff` subtext line when mode/type are known and not `"unknown"`), test green.
- [ ] **Step 5: Commit.**

### Task 15: HeroCarCard — live context + driving-efficiency tile

**Files:**
- Modify: `frontend/src/components/dashboard/HeroCarCard.tsx`
- Test: `frontend/src/components/dashboard/HeroCarCard.test.tsx`

- [ ] **Step 1: Write failing tests** — (a) while charging with `charge_rate` + `charging_estimated_end_at`, the card shows the car-reported rate and an ETA; (b) `battery_care=true` shows a "Battery care" pill; (c) `driving_efficiency` non-null renders a tile with the rolling average converted to the user's unit (mi/kWh from kWh/100km).
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** — add a "Battery care" `Pill` near the charging pill; add an estimated-end line; add a `DrivingEfficiencyTile` (sibling to `MileageYearTile`) that converts `kwh_per_100km → mi/kWh` (`mi/kWh = 62.1371 / kwh_per_100km`) and links to `/driving`. Compare against `nominal_efficiency_mi_per_kwh` (already on the panel).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit.**

### Task 16: `/driving` page + route + nav

**Files:**
- Create: `frontend/src/pages/Driving.tsx`
- Modify: the router (find where routes are declared, e.g. `App.tsx`/`routes.tsx`) + the nav component
- Test: `frontend/src/pages/Driving.test.tsx`

- [ ] **Step 1: Write failing test** — mock `api.getCarTrips` to return two trips; assert the page lists them with converted units and shows a header.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** — a page that (for the user's car(s)) calls `api.getCarTrips`, renders a trip-history list (date, length via `formatDistance`, consumption as mi/kWh, duration, recuperation, kind pill) and a simple inline SVG efficiency sparkline (reuse the `ChargeCurve` SVG approach from `SessionDetail.tsx` as a reference — do not import it; a small local sparkline is fine). Register `/driving` in the router and add a nav link.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit.**

### Task 17: Sync UI — requests-remaining indicator

**Files:**
- Modify: the sync status component/store (`frontend/src/stores/syncStore.ts` + wherever sync status renders)
- Test: the corresponding `.test.tsx`

- [ ] **Step 1: Write failing test** — sync status with `requests_remaining=3` renders "3 remote requests left"; a `sync.refresh_skipped` event surfaces the skip reason.
- [ ] **Step 2–4:** Implement (read `syncStore.ts` for the SSE event handling pattern; add the field + a small indicator), test green.
- [ ] **Step 5: Commit.**

---

## Phase 6 — Integration & polish

### Task 18: Integration probe assertions

**Files:**
- Modify: `backend/tests/integration/test_real_cupra.py`

- [ ] Add gated (`INTEGRATION=1`) assertions that the live adapter returns the new fields with sane types (or `None`), and that `_read_trip` produces a `TripSnapshot` when the account has trip data. Document any field whose live shape differed from Task 0's assumption.
- [ ] Commit.

### Task 19: Full-suite verification

- [ ] **Backend:** `cd backend && pytest backend/tests` → all green. Confirm `test_security_invariants.py` passed (EXEMPT_PATHS hash unchanged).
- [ ] **Frontend:** `cd frontend && npm run lint && npm run typecheck && npm test` → all green.
- [ ] **Manual smoke** (optional, real account): `uvicorn plugtrack.main:create_app --factory --port 9278 --reload` + `npm run dev`; trigger a sync; verify dashboard tile, `/driving`, session detail context, sync quota indicator.
- [ ] Final commit / open PR.

```bash
git add -A && git commit -m "test: integration probe + full-suite verification for telemetry enrichment"
```

---

## Self-Review (author checklist — done at plan-write time)

- **Spec coverage:** charging_mode (T2,T6) ✓; charge context fields (T2,T4,T7,T13,T14) ✓; live dashboard context (T4,T7,T9,T11,T15) ✓; trips persist+history (T1,T2,T3,T7,T9,T10,T16) ✓; requests_remaining display+guard (T2,T5,T7,T8,T11,T17) ✓; /driving page (T16) ✓; both trip kinds, last as headline (T2,T9) ✓; settings keys (T5) ✓; additive migrations (T4) ✓; security hash unchanged (T10,T19) ✓; verify-first probe (T0,T18) ✓.
- **Placeholders:** Implementation steps that depend on local file shapes (orchestrator `force_refresh` signature, worker fixtures, router declaration, syncStore SSE) are flagged "read file first" rather than guessed — these are genuine lookups, not lazy placeholders. All new code (model, adapter helpers, trip capture, dashboard aggregate, endpoint) is given concretely.
- **Type consistency:** `TripSnapshot`/`CarTripSnapshot` field names match across adapter → model → service → API → client. `entry_key` dedup key consistent. `driving_efficiency.{latest_kwh_per_100km, rolling_avg_kwh_per_100km, sample_count}` consistent T9↔T12↔T15.

---

## Parallel / agent-team execution map

Dependencies form waves. Within a wave, tasks are independent and can run on parallel agents.

- **Wave 0 (serial, blocking):** T0 (probe) → T1 → T2. These define the dataclasses everything imports.
- **Wave 1 (parallel):** T3, T4, T5 (persistence + settings — independent files).
- **Wave 2 (parallel):** T6, T7, T8 (services — T7 depends on T3/T4; T8 on T5; T6 on T2). Run after Wave 1.
- **Wave 3 (parallel):** T9 then T10, T11 (API depends on services). T9 before T11 (dashboard serialisation).
- **Wave 4 (parallel):** T12 first (client types), then T13–T17 in parallel (distinct components/files).
- **Wave 5 (serial):** T18, T19 (integration + full-suite gate).

**Suggested roles per task:** a **dev** agent implements steps 1–4 (TDD: failing test → impl → green), a **review** agent runs the two-stage review from `superpowers:subagent-driven-development` (spec-compliance + code-quality), and a **qa** agent runs the full relevant suite + lint/typecheck before the wave advances. Frontend tasks additionally run `npm run typecheck` (use `tsc -b`, stricter — see project memory).
