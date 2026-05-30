# pycupra Charge-Context Enrichment — Implementation Plan (REVISED post-probe)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Surface the pycupra charge-context fields that are confirmed-supported on the live vehicle — finish the half-built `charging_mode`, and add `battery_care`, `max_charge_current` (enum string), and live `charging_estimated_end_time` — across the dashboard, sessions list, and session detail.

**Architecture:** All new provider data enters through the single adapter boundary (`plugins/pycupra/adapter.py` → `VehicleState`). New columns reach existing tables via the established `_apply_additive_migrations` hook in `main.py`. No new tables, no new routes, no new settings.

**Tech Stack:** FastAPI, async SQLAlchemy (backend); React 19, Vite, Tailwind 4, zustand, vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-05-30-pycupra-telemetry-enrichment-design.md` — build to **§0 (REVISED SCOPE)**, not the original §1–§12.

**Probe outcome (already done — semantics are locked, do NOT re-probe):**
- `charging_mode` property → `"Timer"` / `"manual"` (capitalised; `.lower()` then validate).
- `charging_battery_care` → `bool`.
- `charge_max_ampere` → **enum STRING** `"maximum"`/`"reduced"` (NOT amps → VARCHAR column).
- `charging_estimated_end_time` → `datetime` (already tz-aware).
- DROPPED (unsupported on the account): all trips, `requests_remaining`, `charge_rate`, `min_charge_level`.

**Conventions (from CLAUDE.md — non-negotiable):** every query filters `user_id`; distances in km with `_km` suffix; never touch `services/cost.py`; never add to `EXEMPT_PATHS` (this plan adds no route, so the security-invariant hash MUST stay unchanged); tests use `test_engine`/`test_sessionmaker` from `conftest.py`, never a real DB.

---

## Task 1: `VehicleState` charge-context fields

**Files:**
- Modify: `backend/plugtrack/plugins/pycupra/models.py`
- Test: `backend/tests/test_pycupra_adapter.py`

- [ ] **Step 1: Write the failing test** (append)

```python
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
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest backend/tests/test_pycupra_adapter.py -k charge_context_fields -v`
Expected: FAIL (unexpected keyword / attribute).

- [ ] **Step 3: Implement** — append to `VehicleState` (frozen dataclass; all current fields are required and keyword-constructed in the adapter, so defaulted fields at the end are safe):

```python
    charging_mode_raw: Optional[str] = None
    battery_care: Optional[bool] = None
    max_charge_current: Optional[str] = None
    charging_estimated_end_at: Optional[datetime] = None
```

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/plugins/pycupra/models.py backend/tests/test_pycupra_adapter.py
git commit -m "feat(pycupra): add charge-context fields to VehicleState"
```

---

## Task 2: Adapter reads charge-context + mode normaliser

**Files:**
- Modify: `backend/plugtrack/plugins/pycupra/adapter.py`
- Test: `backend/tests/test_pycupra_adapter.py`

- [ ] **Step 1: Write the failing tests** — use a fake Vehicle honouring the `is_<name>_supported` contract (a property whose `is_<name>_supported` is `False` returns the default in `_safe_attr`).

```python
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
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** in `adapter.py`:

```python
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
```

In `fetch_vehicle_state`, add these kwargs to the `VehicleState(...)` construction. `charge_max_ampere` is a string enum — keep it as a string (do NOT coerce to float):

```python
        charging_mode_raw=_normalise_charging_mode(_safe_attr(vehicle, "charging_mode")),
        battery_care=_coerce_optional_bool(_safe_attr(vehicle, "charging_battery_care")),
        max_charge_current=(
            str(_safe_attr(vehicle, "charge_max_ampere"))
            if _safe_attr(vehicle, "charge_max_ampere") not in (None, "")
            else None
        ),
        charging_estimated_end_at=_coerce_optional_datetime(
            _safe_attr(vehicle, "charging_estimated_end_time")),
```

> `charging_mode_raw` now holds the already-normalised value (`manual|timer|profile|unknown`). Downstream code uses it directly.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_pycupra_adapter.py -v` (all, incl. pre-existing).

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/plugins/pycupra/adapter.py backend/tests/test_pycupra_adapter.py
git commit -m "feat(pycupra): adapter reads charging_mode/battery_care/max_current/est_end"
```

---

## Task 3: Additive columns on `ChargingSession` + `CarStateSnapshot`

**Files:**
- Modify: `backend/plugtrack/models/charging_session.py`, `backend/plugtrack/models/car_state.py`, `backend/plugtrack/main.py`
- Test: `backend/tests/test_additive_migrations.py` (create)

- [ ] **Step 1: Write the failing test.** If no `seeded_user_car` fixture exists in `conftest.py`, add one (insert a `User` + `Car`, return `(user_id, car_id)`) following the existing fixture style.

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
            charging_mode="timer", battery_care=True, max_charge_current="maximum")
        s.add(row); await s.commit(); await s.refresh(row)
        assert row.battery_care is True
        assert row.max_charge_current == "maximum"


@pytest.mark.asyncio
async def test_car_state_has_live_context_columns(test_sessionmaker, seeded_user_car):
    _uid, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        row = CarStateSnapshot(
            car_id=car_id, last_battery_care=True, last_max_charge_current="reduced",
            last_charging_estimated_end_at=dt.datetime.now(dt.timezone.utc))
        s.add(row); await s.commit(); await s.refresh(row)
        assert row.last_max_charge_current == "reduced"
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement.**

In `charging_session.py`, after the `charging_mode` column add:

```python
    battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    max_charge_current: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
```

In `car_state.py`, after `last_charging_power_kw` add (and add `Boolean` to its sqlalchemy import):

```python
    last_battery_care: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_max_charge_current: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    last_charging_estimated_end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

In `main.py` `_apply_additive_migrations`, extend `additions`:

```python
        ("charging_session", "battery_care", "BOOLEAN"),
        ("charging_session", "max_charge_current", "VARCHAR(16)"),
        ("car_state", "last_battery_care", "BOOLEAN"),
        ("car_state", "last_max_charge_current", "VARCHAR(16)"),
        ("car_state", "last_charging_estimated_end_at", "DATETIME"),
```

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_additive_migrations.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/models/ backend/plugtrack/main.py backend/tests/test_additive_migrations.py backend/tests/conftest.py
git commit -m "feat(models): charge-context columns w/ additive migration"
```

---

## Task 4: Synthesiser populates `charging_mode` + context

**Files:**
- Modify: `backend/plugtrack/services/session_synthesiser.py`
- Test: `backend/tests/test_session_synthesiser.py`

- [ ] **Step 1: Write the failing test** — feed telemetry with `charging_mode_raw="timer"`, `battery_care=True`, `max_charge_current="maximum"`; drive plug-in→charging; assert the emitted open-session payload carries them.

```python
def test_open_session_payload_carries_charging_mode_and_context():
    # Reuse this file's existing telemetry/sample builder; set on the sample:
    #   charging_mode_raw="timer", battery_care=True, max_charge_current="maximum"
    assert open_payload["charging_mode"] == "timer"
    assert open_payload["battery_care"] is True
    assert open_payload["max_charge_current"] == "maximum"
```

> Read `test_session_synthesiser.py` first to reuse its sample builder and the way it captures emitted payloads. The synthesiser is a pure state machine (no DB).

- [ ] **Step 2: Run, expect failure** (payload still `"unknown"`/missing keys).

- [ ] **Step 3: Implement** — at the four payload dicts (lines ~163–216) replace `"charging_mode": "unknown"` with the telemetry value and add the two context keys:

```python
                "charging_mode": telemetry.charging_mode_raw or "unknown",
                "battery_care": telemetry.battery_care,
                "max_charge_current": telemetry.max_charge_current,
```

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_session_synthesiser.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/session_synthesiser.py backend/tests/test_session_synthesiser.py
git commit -m "feat(sessions): populate charging_mode + context from telemetry"
```

---

## Task 5: Worker persists session context + live state

**Files:**
- Modify: `backend/plugtrack/services/sync_worker.py`
- Test: `backend/tests/test_sync_worker.py`

- [ ] **Step 1: Write the failing test** — after `_handle_open_session`, the new `ChargingSession` row has `battery_care` + `max_charge_current` from the payload; and the persisted `CarStateSnapshot` carries the live context fields.

```python
@pytest.mark.asyncio
async def test_open_session_persists_context(worker, seeded_user_car, make_open_payload, make_telemetry):
    # build payload with battery_care=True, max_charge_current="maximum"
    # call worker._handle_open_session(...) per this file's existing harness
    # then load the ChargingSession row and assert:
    assert row.battery_care is True
    assert row.max_charge_current == "maximum"
```

> Read `test_sync_worker.py` for the worker fixture + payload/telemetry builders and the existing `CarStateSnapshot` upsert test, and mirror them.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** —

In `_handle_open_session` (~line 513) add to the `ChargingSession(...)` constructor:

```python
                battery_care=payload.get("battery_care"),
                max_charge_current=payload.get("max_charge_current"),
```

Wherever the worker upserts `CarStateSnapshot` (grep `CarStateSnapshot` in the worker), set the live fields from telemetry:

```python
            snapshot.last_battery_care = telemetry.battery_care
            snapshot.last_max_charge_current = telemetry.max_charge_current
            snapshot.last_charging_estimated_end_at = telemetry.charging_estimated_end_at
```

(Match the assignment style already used for `last_charging_power_kw` etc.)

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_sync_worker.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/sync_worker.py backend/tests/test_sync_worker.py
git commit -m "feat(sync): persist session + live charge-context"
```

---

## Task 6: Dashboard service surfaces live context

**Files:**
- Modify: `backend/plugtrack/services/dashboard_service.py`
- Test: `backend/tests/test_dashboard_service.py`

- [ ] **Step 1: Write the failing test** — with orchestrator live state carrying `last_battery_care`/`last_max_charge_current`/`last_charging_estimated_end_at`, the `CarPanel` exposes `battery_care`, `max_charge_current`, `charging_estimated_end_at`.

```python
@pytest.mark.asyncio
async def test_car_panel_includes_live_charge_context(test_sessionmaker, seeded_user_car, fake_orchestrator_with_state):
    # fake orchestrator.get_state(car_id) returns a state with
    #   last_battery_care=True, last_max_charge_current="maximum",
    #   last_charging_estimated_end_at=<dt>
    summary = await dashboard_summary(session, user_id=user_id, orchestrator=orch)
    panel = summary.cars[0]
    assert panel.battery_care is True
    assert panel.max_charge_current == "maximum"
    assert panel.charging_estimated_end_at is not None
```

> Reuse this file's existing orchestrator-stub pattern (it already injects live state for `electric_range_km`/`charging_power_kw`).

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — add to `CarPanel`: `battery_care: Optional[bool] = None`, `max_charge_current: Optional[str] = None`, `charging_estimated_end_at: Optional[datetime] = None`. In the per-car loop where live fields are read from `live` via `getattr(...)`, add:

```python
                battery_care = getattr(live, "last_battery_care", None)
                max_charge_current = getattr(live, "last_max_charge_current", None)
                charging_estimated_end_at = getattr(
                    live, "last_charging_estimated_end_at", None)
```

and pass them into the `CarPanel(...)` construction (default `None` before the `if orchestrator` block, like the other live fields).

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/test_dashboard_service.py -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/services/dashboard_service.py backend/tests/test_dashboard_service.py
git commit -m "feat(dashboard): expose live battery-care + current cap + est-end"
```

---

## Task 7: API payloads

**Files:**
- Modify: `backend/plugtrack/api/routes/sessions.py`
- Test: `backend/tests/api/test_sessions.py`, `backend/tests/api/test_dashboard.py`

- [ ] **Step 1: Write failing tests** — `GET /api/sessions/{id}` returns `battery_care` + `max_charge_current`; `PUT` accepts them; `GET /api/dashboard` car panel includes `battery_care`/`max_charge_current`/`charging_estimated_end_at` (the dashboard route returns `DashboardSummary.to_dict()` via `asdict`, so new `CarPanel` fields serialise automatically — assert their presence).

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** — add `battery_care: Optional[bool]` and `max_charge_current: Optional[str]` to `ChargingSessionPayload` (response) + the serialiser (~line 192), and to `SessionUpdateRequest` + the update handler (~line 367), following the existing per-field mapping. Dashboard needs no route change — just confirm + test.

- [ ] **Step 4: Run, expect pass** — `pytest backend/tests/api -v`. **Then `pytest backend/tests/api/test_security_invariants.py -v` MUST still pass** (no route/EXEMPT_PATHS change).

- [ ] **Step 5: Commit**

```bash
git add backend/plugtrack/api/routes/sessions.py backend/tests/api/
git commit -m "feat(api): expose battery_care + max_charge_current on sessions"
```

---

## Task 8: Frontend client types

**Files:**
- Modify: `frontend/src/api/client.ts`
- Verify: `npm run typecheck`

- [ ] **Step 1:** Add `battery_care: boolean | null` and `max_charge_current: string | null` to `ChargingSessionPayload` and `SessionUpdateRequest`; add `battery_care`, `max_charge_current`, `charging_estimated_end_at: string | null` to `DashboardCarPanel`.
- [ ] **Step 2:** `npm run typecheck` (use `tsc -b` — stricter; see project memory). Additive-optional fields should typecheck clean.
- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts && git commit -m "feat(ui): client types for charge context"
```

---

## Task 9: SessionDetail — Charge context section + edit inputs

**Files:**
- Modify: `frontend/src/pages/SessionDetail.tsx`
- Test: `frontend/src/pages/SessionDetail.test.tsx`

- [ ] **Step 1: Write failing test** — render a session with `charging_mode="timer"`, `charging_type="ac"`, `battery_care=true`, `max_charge_current="maximum"`; assert a "Charge context" section shows "Timer", "AC", "Battery care", "Max current: maximum".
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** — add a `ChargeContext` section (mirror the existing `ChargeMechanics` structure with `StatTile`s), suppressed when mode is `"unknown"`/`null` AND type is `"unknown"` AND `battery_care`/`max_charge_current` are null. Map `max_charge_current` to a readable label (`"maximum"` → "Maximum", `"reduced"` → "Reduced", else the raw string). Add `battery_care` (checkbox) + `max_charge_current` (text/select: maximum|reduced) inputs to `SessionEditForm`, include them in the `SessionUpdateRequest` body.
- [ ] **Step 4: Run, expect pass** — `npm test -- SessionDetail`.
- [ ] **Step 5: Commit.**

---

## Task 10: Sessions list — mode/type hint

**Files:**
- Modify: `frontend/src/pages/Sessions.tsx`
- Test: `frontend/src/pages/Sessions.test.tsx`

- [ ] **Step 1: Write failing test** — a synthesis row with `charging_mode="timer"`, `charging_type="ac"` renders a `Timer · AC` hint.
- [ ] **Step 2–4:** In `SessionRow`, append a ` · Timer · AC`-style fragment to the existing `kWh @ tariff` subtext line when mode/type are known and not `"unknown"`. Test green.
- [ ] **Step 5: Commit.**

---

## Task 11: HeroCarCard — battery-care pill + estimated end

**Files:**
- Modify: `frontend/src/components/dashboard/HeroCarCard.tsx`
- Test: `frontend/src/components/dashboard/HeroCarCard.test.tsx`

- [ ] **Step 1: Write failing tests** — (a) `battery_care=true` renders a "Battery care" pill; (b) while charging with `charging_estimated_end_at` set, the card shows an ETA (e.g. "Full ~18:42" or relative).
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** — add a "Battery care" `Pill` (amber/slate) near the existing charging pill when `car.battery_care`; add an estimated-end line in the stats grid (format the ISO time with the existing `formatRelative` or a short local time) shown when charging and `charging_estimated_end_at` is set.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit.**

---

## Task 12: Full-suite verification

- [ ] **Backend:** `cd backend && pytest backend/tests` → all green; confirm `test_security_invariants.py` passed (EXEMPT_PATHS hash unchanged).
- [ ] **Frontend:** `cd frontend && npm run lint && npm run typecheck && npm test` → all green.
- [ ] **Manual smoke (optional):** `uvicorn plugtrack.main:create_app --factory --port 9278 --reload` + `npm run dev`; trigger a sync; verify the dashboard battery-care pill + est-end, the sessions-list hint, and the session-detail Charge context section.
- [ ] Final commit / open PR.

---

## Self-Review (author checklist)

- **Spec §0 coverage:** charging_mode fill (T2,T4) ✓; battery_care (T2–T11) ✓; max_charge_current as string (T2,T3,T5,T7,T9) ✓; live charging_estimated_end_time (T2,T3,T5,T6,T11) ✓; surfaces dashboard+list+detail (T9,T10,T11) ✓; no new table/route/settings ✓; security hash unchanged (T7,T12) ✓.
- **Dropped scope absent:** no `CarTripSnapshot`, no `/driving`, no trips endpoint, no `requests_remaining`, no `charge_rate`/`min_charge_level`, no new settings keys. ✓
- **Type consistency:** `max_charge_current` is `str`/VARCHAR(16) everywhere (model, adapter, payload, client, UI) — NOT the original Float. `charging_mode_raw` is pre-normalised in the adapter and consumed directly by the synthesiser. ✓

---

## Parallel / agent-team execution map

- **Wave A (serial):** T1 → T2 (adapter dataclass + coercion; T2 depends on T1).
- **Wave B (parallel after A):** T3 (persistence) and T4 (synthesiser) — independent files.
- **Wave C (serial after B):** T5 (worker) → T6 (dashboard) → T7 (API).
- **Wave D (parallel after C):** T8 first (client types), then T9, T10, T11 (distinct components).
- **Wave E (serial):** T12 (full-suite gate).

Per task: a **dev** agent runs the TDD steps; a **review** agent re-runs the named tests + checks conventions; a **qa** gate runs the relevant suite before the wave advances. Sequential within a single git branch to avoid index races; parallelism only across genuinely independent files.
