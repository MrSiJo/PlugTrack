# Design: Surface richer pycupra telemetry in PlugTrack

- **Date:** 2026-05-30
- **Status:** Approved design, pre-implementation
- **Author:** Simon + Claude
- **Related:** pycupra bumped to v0.2.32 (commits `d45b25d`, `29c4f45`); recent
  session work (`837e76f` kwh_calculated, `5f1fea7` per-session range/efficiency).

## 1. Motivation

pycupra v0.2.32 exposes ~267 Vehicle properties. PlugTrack currently consumes
~17 of them (`plugins/pycupra/adapter.py`). Several unused fields map directly
onto things PlugTrack already tries to track:

- `charging_session.charging_mode` is a real column (and is in the API + edit
  form + UI) but the synthesiser **hardcodes `"unknown"`** because the adapter
  never reads pycupra's `charging_mode` — a half-built feature.
- pycupra reports **driving/trip efficiency** (car-measured kWh/100km, trip
  length, duration, recuperation) — the real-world complement to the SoC-delta
  energy estimate that recent commits introduced.
- pycupra reports **`requests_remaining`** (remaining remote-request quota); the
  orchestrator currently consumes `force_refresh` quota blindly.
- Several fields **explain a charge** (`charge_rate`, `charge_max_ampere`,
  `charging_battery_care`/`slow_charge`, `min_charge_level`,
  `charging_estimated_end_time`) so a slow/limited session is self-documenting.

This is intentionally additive enrichment. pycupra still exposes **no charging
history** (`plugins/contracts.py` is correct); we enrich synthesised sessions
and add a new trip-history data kind — we do not replace synthesis.

## 2. Scope

Single combined spec (one implementation plan). Everything flows through the one
adapter boundary (`plugins/pycupra/adapter.py` → `VehicleState`); no other module
learns new pycupra types.

Four buckets:

1. **Live charging context** (per-car, while plugged/charging) → dashboard
   `HeroCarCard`.
2. **Per-session context** (snapshot at charge start) → sessions list +
   `SessionDetail`.
3. **Driving/trip efficiency** (per-drive — a new persisted data kind) →
   `CarTripSnapshot` table, dashboard tile, new `/driving` page.
4. **Operational** — `requests_remaining` → sync UI + a `force_refresh` guard.

### Out of scope

- Charging-history import (pycupra has none).
- Climate / door / window / combustion telemetry (irrelevant to charge tracking).
- Backfilling `charging_mode` on historical synthesised sessions (they stay
  `"unknown"`; only new sessions get the value).

## 3. Field-semantics risk (verify-first)

Several pycupra fields have **uncertain units/shape**. The implementation plan's
**first task is an `INTEGRATION=1` probe** (`scripts/pycupra_probe.py` against
`.env.probe`) to confirm these before coercion logic is finalised. Assumptions
below are explicit and marked **[VERIFY]**:

| Field | Assumption | Risk |
|---|---|---|
| `charge_rate` | numeric; **[VERIFY]** units (%/h vs km/h) | wrong unit label in UI |
| `charge_max_ampere` | enum string (`"maximum"`/`"reduced"`) or int amps; coerce to Float amps or keep raw string **[VERIFY]** | type mismatch |
| `charging_mode` / `charging_preferred_mode` | strings mappable to `manual\|timer\|profile` **[VERIFY]** exact values | mode stays `unknown` |
| `charging_battery_care` / `slow_charge` | boolean-ish | low |
| `charging_estimated_end_time` | ISO datetime or epoch **[VERIFY]** | parse failure → None |
| `requests_remaining` | int **[VERIFY]** (may be nested dict) | guard mis-fires |
| `trip_last_entry` / `trip_last_cycle_entry` | dict with a timestamp/id for **dedup key** **[VERIFY]** | duplicate/missing trips |

All reads go through the existing `_safe_attr` + `is_<name>_supported` guard, so
an unsupported car or a probe surprise degrades to `None` rather than raising.

## 4. Data layer — adapter & `VehicleState`

`plugins/pycupra/models.py` — extend `VehicleState` (frozen dataclass) with:

- `charging_mode_raw: Optional[str]`
- `charge_rate: Optional[float]`
- `max_charge_current: Optional[float]`   *(coerced from `charge_max_ampere`; if
  pycupra returns an enum string, store the raw string in `raw_payload` and leave
  this None — decided at probe time)*
- `battery_care: Optional[bool]`
- `min_charge_level: Optional[int]`
- `charging_estimated_end_at: Optional[datetime]`
- `requests_remaining: Optional[int]`
- `trip_last: Optional[TripSnapshot]`
- `trip_last_cycle: Optional[TripSnapshot]`

New frozen dataclass `TripSnapshot`:

```
kind: str                                   # "last" | "cycle"
entry_key: str                              # dedup key from trip_last_entry [VERIFY]
captured_at: datetime
avg_consumption_kwh_per_100km: Optional[float]
total_consumption_kwh: Optional[float]
length_km: Optional[float]
duration_min: Optional[int]
avg_speed_kmh: Optional[float]
avg_recuperation_kwh_per_100km: Optional[float]
```

`plugins/pycupra/adapter.py` — `fetch_vehicle_state` reads the new properties via
`_safe_attr`, adds a `_read_trip(vehicle, kind)` helper that builds a
`TripSnapshot` from `trip_last_*` / `trip_last_cycle_*`, and a
`_normalise_charging_mode(raw) -> str` mapping to `manual|timer|profile|unknown`.
`discover()`/`get_*` call list extended if a trip-specific fetch is required
(confirm at probe time; trip data may already populate via `get_statusreport`).

## 5. Persistence

The lifespan handler already runs `Base.metadata.create_all` (new tables) **and**
`_apply_additive_migrations` (idempotent `ALTER TABLE ADD COLUMN` keyed by
`PRAGMA table_info`) in `main.py`. Both new-column and new-table paths are
established.

### 5.1 `ChargingSession` (additive columns)

New nullable columns + matching `_apply_additive_migrations` entries:

- `max_charge_current_a` — `Float`
- `battery_care` — `Boolean` (nullable; null = unknown)
- `charging_mode` — **already exists**, now populated.

`min_charge_level` and any other forensic extras go into the existing
`raw_payload` JSON, not dedicated columns (YAGNI — not surfaced).

### 5.2 `CarStateSnapshot` (additive columns — live dashboard rehydrate)

New nullable columns + migration entries:

- `last_charge_rate` — `Float`
- `last_charging_estimated_end_at` — `DateTime(timezone=True)`
- `last_battery_care` — `Boolean`
- `last_min_charge_level` — `Integer`
- `last_max_charge_current_a` — `Float`
- `last_requests_remaining` — `Integer`

Mirrored on the orchestrator's in-memory `CarSyncState` so the request hot-path
serves them without a DB read, and rehydrated on startup (same pattern as
existing `last_*` fields).

### 5.3 New model `CarTripSnapshot` (new table via `create_all`)

```
id: int PK
user_id: int FK(user.id)            # multi-user isolation — every query filters this
car_id: int FK(car.id)
kind: str                           # "last" | "cycle"
entry_key: str                      # dedup key
captured_at: datetime
avg_consumption_kwh_per_100km: Optional[float]
total_consumption_kwh: Optional[float]
length_km: Optional[float]          # _km suffix per distance convention
duration_min: Optional[int]
avg_speed_kmh: Optional[float]
avg_recuperation_kwh_per_100km: Optional[float]
created_at: datetime
```

Partial unique index `uq_trip_car_kind_entry` on `(car_id, kind, entry_key)` so
re-polling the same "last trip" is idempotent (mirrors the session
`telematics_session_id` unique-index pattern). Distance stored in km (`length_km`)
per the distance-storage rule; UI converts.

## 6. Services

- **`services/session_synthesiser.py`** — replace the four hardcoded
  `"charging_mode": "unknown"` (lines ~164/175/198/216) with the normalised value
  from telemetry; thread `battery_care` + `max_charge_current` into the
  open-session payload dicts.
- **`services/sync_worker.py`** —
  - `_handle_open_session` writes `charging_mode`, `max_charge_current_a`,
    `battery_care` onto the new `ChargingSession`.
  - Each sync persists the new `CarStateSnapshot` live fields.
  - **New step** `_capture_trips(car, telemetry)` upserts `CarTripSnapshot` rows
    from `telemetry.trip_last` / `trip_last_cycle`, deduped on
    `(car_id, kind, entry_key)` via `INSERT ... ON CONFLICT DO NOTHING`
    (or get-or-create). Always filtered/owned by `car.user_id`.
- **`services/sync_orchestrator.py`** — cache `requests_remaining` on
  `CarSyncState`; **`force_refresh` guard**: before delegating to the adapter's
  `setRefresh`, if `requests_remaining` is known and `<= reserve`, skip and emit a
  `sync.refresh_skipped` event (reason `low_quota`) instead of consuming quota.
  `reserve` comes from a new `Settings` key.
- **`services/dashboard_service.py`** — extend the single aggregation pass to
  include the new live context fields and a **driving-efficiency aggregate**:
  latest `last`-kind trip + rolling N-day average of `last`-kind trips +
  `sample_count`, per car.

### 6.1 Settings

New seeded `Settings` key `force_refresh_min_remaining_requests` (default `2`),
read via `Settings.get_setting` (no hard-coded constant per project convention).
Rolling-average window for driving efficiency: new key
`driving_efficiency_window_days` (default `30`).

## 7. API (flat shape, consistent with `client.ts`)

- **`DashboardCarPanel`** += `charge_rate`, `charging_estimated_end_at`,
  `battery_care`, `min_charge_level`, `max_charge_current_a`,
  `requests_remaining`, and a nested `driving_efficiency` object:
  `{ latest_kwh_per_100km, rolling_avg_kwh_per_100km, sample_count }`.
- **`ChargingSessionPayload`** += `battery_care`, `max_charge_current_a`
  (`charging_mode` already present). `SessionUpdateRequest` accepts
  `battery_care` + `max_charge_current_a` so manual edits work.
- **New `GET /api/cars/{id}/trips`** (authed, user-filtered) → recent
  `CarTripSnapshot` rows for the `/driving` page. Supports `?kind=` and a limit.
  Registered in `create_app()`. **Not** added to either `EXEMPT_PATHS` set →
  `test_security_invariants` hash is **unchanged**.
- **Sync status payload** (existing sync route) += `requests_remaining` and the
  last refresh-skip reason.

## 8. Frontend

- **`HeroCarCard`** (`components/dashboard/`): while charging, show car-reported
  `charge_rate` (unit per probe) and estimated end time; a **"Battery care"** pill
  when active; min-charge-level when set. Always (when data exists) a
  **"Driving efficiency"** tile — latest trip + rolling average converted to the
  user's unit (`mi/kWh` via `settingsStore`), compared to the car's existing
  `nominal_efficiency_mi_per_kwh`.
- **`Sessions` list rows** (`pages/Sessions.tsx`): a compact `Timer · AC`-style
  mode/type hint in the existing second subtext line.
- **`SessionDetail`** (`pages/SessionDetail.tsx`): a new **"Charge context"**
  section beside "Charge mechanics" — mode, type, battery-care, current cap — so a
  slow/limited charge is self-explaining. Edit form gains battery-care + max-current
  inputs.
- **New `/driving` page**: trip-history list (date, length, consumption, duration,
  recuperation, kind) with a simple efficiency sparkline; reached from the
  dashboard tile. New route + nav entry; typed client method `api.getCarTrips`.
- **Sync UI**: "N remote requests remaining" indicator; when the guard skips a
  refresh, show the reason.

All distances rendered via `formatDistance()` / `kmToMi`; all units honour the
`distance_unit` setting.

## 9. Trip-kind policy

Persist **both** `last` (single drive) and `cycle` (since-reset) snapshots. The
**dashboard headline + rolling average use `last`-kind** trips (per-drive
granularity → real history). `cycle` is stored for reference and may be shown on
`/driving` as the car's own long-term figure. Rolling average is computed from
stored `last` trips over `driving_efficiency_window_days`.

## 10. Testing

**Backend (`pytest backend/tests`, no real DB):**
- adapter: new-field coercion + trip building with mocked `Vehicle` /
  `is_*_supported`; `_normalise_charging_mode` table.
- synthesiser: `charging_mode` normalisation replaces `unknown`.
- worker: session-context columns written; `_capture_trips` dedup/idempotency.
- orchestrator: `force_refresh` skips when `requests_remaining <= reserve`; emits
  `sync.refresh_skipped`.
- dashboard_service: driving-efficiency latest + rolling average + sample_count.
- API: new payload fields; `/api/cars/{id}/trips` happy path + user isolation.
- `test_security_invariants`: **must still pass unchanged** (new route authed).

**Frontend (vitest):** `HeroCarCard` new live fields + driving tile;
`SessionDetail` charge-context section; `/driving` page render.

**Integration (gated `INTEGRATION=1`):** probe assertions for the §3 field
semantics, extending `tests/integration/test_real_cupra.py`.

## 11. Migration / rollout

- New columns added idempotently via `_apply_additive_migrations`; new table via
  `create_all`. No Alembic. Existing rows keep `NULL` for new columns.
- Backward compatible: all new session/state columns nullable; old sessions render
  unchanged (sections suppress when every field is null, matching existing
  `ChargeMechanics` behaviour).
- New `Settings` keys seeded by `seed_defaults`.

## 12. Open risks

- Field semantics (§3) — mitigated by the probe-first task.
- `charge_max_ampere` may be an enum, not amps — fallback: keep raw in
  `raw_payload`, leave `max_charge_current_a` null, label UI accordingly.
- Trip dedup depends on a stable `entry_key`; if pycupra exposes no stable id,
  fall back to `captured_at` rounded to the minute (documented at probe time).
