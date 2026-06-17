# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Repository Layout

PlugTrack v2 is a two-service container app:

- **`backend/`** — FastAPI + async SQLAlchemy + APScheduler. The Python package lives in `backend/plugtrack/`. Tests in `backend/tests/`.
- **`frontend/`** — React 19 + Vite + Tailwind 4 + zustand. Source in `frontend/src/`.
- **`compose.yaml`** — pulls pre-built images from GHCR (the default `docker compose up -d` target).
- **`compose-dev.yaml`** — source-build compose; used by `scripts/deploy.{ps1,sh}` and any local `docker compose -f compose-dev.yaml ...` flow.
- **`scripts/deploy.{ps1,sh}`** — production deploy entry points; build from source via `compose-dev.yaml` and refuse to run against the local Docker context.
- **`.github/workflows/build-images.yml`** — multi-arch build + publish of `ghcr.io/mrsijo/plugtrack-{api,ui}` on push to `main` and on `v*.*.*` tags.

Note: `docs/` and `legacy/` are gitignored. If they exist locally they hold design specs and the v1 Flask codebase respectively, but neither is part of the tracked repo. Treat them as read-only personal scratch when present, and do not assume they exist.

## Common Commands

### Backend dev

```bash
cd backend
pip install -r requirements.txt

# Dev server (factory mode — required so the lifespan handler runs)
uvicorn plugtrack.main:create_app --factory --port 9278 --reload

# Tests (default suite — integration is gated, see below)
pytest backend/tests
pytest backend/tests/test_dashboard_service.py     # single file
pytest -k cost                                     # by name pattern
```

### Frontend dev

```bash
cd frontend
npm install
npm run dev          # Vite dev server on :5173, proxies /api → :9278
npm test             # vitest
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
```

### Deploy

```bash
docker context use <your-remote-context>   # NEVER deploy against `default`
scripts/deploy.ps1                          # PowerShell
scripts/deploy.sh                           # bash
```

The deploy scripts hard-fail when the active Docker context is `default`.

## High-Level Architecture

### Application factory + lifespan
`backend/plugtrack/main.py:create_app()` is the single source of truth for app wiring. The lifespan handler:

1. **Asserts single-worker exclusivity** (see "Multi-worker tripwire" below).
2. Runs `Base.metadata.create_all` so the schema exists in dev (production uses the same path on first boot).
3. Calls `seed_defaults` to insert any missing rows in the `setting` catalogue.
4. Wires three long-lived services into `app.state`:
   - `event_bus` — pub/sub fan-out for SSE clients.
   - `sync_orchestrator` — per-car mutex + state cache; serialises syncs per vehicle and surfaces `CarSyncState` to the dashboard.
   - `sync_scheduler` — APScheduler-backed adaptive cadence (faster polls while charging, backs off when idle / on auth failure).

Routes are registered at the bottom of `create_app()`; every blueprint must be added there, never on import. The `EXEMPT_PATHS` sets in `api/auth_middleware.py` and `security/csrf.py` gate which paths bypass auth/CSRF — see "EXEMPT_PATHS pinning" below.

### Layered data flow
`Route → Service (async functions / dataclasses) → Model → SQLAlchemy`. Routes stay thin; business logic lives in `backend/plugtrack/services/`. **Always filter queries by `request.state.user_id`** — multi-user isolation is enforced at the query level, not by the database.

Key services:

- `services/sync_orchestrator.py`, `services/sync_scheduler.py`, `services/sync_worker.py` — the sync stack. Worker reads pycupra adapter, runs the state machine, persists sessions, emits events.
- `services/session_synthesiser.py` — pure state-machine that turns a raw SoC/charging-status sample stream into one `ChargingSession` per plug-in cycle.
- `services/cost.py` — single source of truth for cost computation (see "Cost precedence" below).
- `services/location_clustering.py`, `services/geocoding.py` — auto-cluster plug-in coords into per-user `Location` rows; reverse-geocode addresses on first sighting.
- `services/dashboard_service.py` — single AsyncSession aggregation pass for the v1 dashboard (cars panel + recent sessions + lifetime totals + top locations).
- `services/event_bus.py` — `EventBus.publish(event)` / `subscribe(job_id)` pair backing SSE.
- `services/auth_service.py` — bootstrap + login + password hashing.

### Frontend
React 19 + zustand stores (`frontend/src/stores/`) with one store per domain (auth, settings, sync, cars, sessions). Pages in `frontend/src/pages/`, shared components in `frontend/src/components/`, the typed API client in `frontend/src/api/client.ts`. Tailwind 4 (no preprocessor); dark mode via `theme.ts` applied to `<html>`. Vitest + Testing Library for tests.

JSON endpoints follow a flat shape — keep new APIs consistent with what `client.ts` exposes.

## Conventions to Follow

### Multi-worker tripwire
Backend MUST run with `WEB_CONCURRENCY=1` (or unset). The lifespan handler asserts this AND acquires a filesystem lock at `/tmp/plugtrack.lock` so direct `--workers N` invocations also fail — only the first worker gets the lock, the rest crash. This is non-negotiable: SQLite + the in-process APScheduler are not multi-worker safe.

### Distance storage rule
All distance columns are stored in **kilometres** with a `_km` suffix (`odometer_at_session_km`, `radius_m` is the metres exception used for the clustering radius only). UI converts to the user's display unit via the `distance_unit` setting (default `mi`) using `formatDistance()` from `frontend/src/stores/settingsStore.ts`. pycupra returns distance in km natively, so no conversion happens server-side.

### Cost precedence
The cost-precedence rule is implemented exactly once in `backend/plugtrack/services/cost.py:compute_session_cost`. Order of resolution:

1. `total_cost_pence_override` → `cost_basis = "override_total"`
2. `cost_per_kwh_override_p` → `"override_per_kwh"`
3. Location with `is_free=True` → `"location_free"` (cost_pence = 0)
4. Location with `default_cost_per_kwh_p` → `"location_rate"`
5. Settings `default_home_rate_p_per_kwh` → `"home_rate"`
6. Otherwise → `"unknown"` (cost_pence = NULL)

User overrides are sacred — re-syncs MUST NOT overwrite them. See spec §3.3 for the full rationale.

### EXEMPT_PATHS pinning
`backend/tests/api/test_security_invariants.py` pins a SHA-256 of the union of `EXEMPT_PATHS` from both the auth and CSRF middlewares. Extending either set requires:

1. Updating the path lists in their respective middleware modules.
2. Regenerating the hardcoded `EXPECTED_EXEMPT_HASH` constant in the invariants test.
3. **Explicit user sign-off** — the comment block in the test calls this out as a manual-review step.

The test runs in the default suite, so a drift will fail CI immediately.

### Integration test gate
`backend/tests/integration/` contains tests that exercise real network paths (currently a real-account pycupra probe). They are gated behind `INTEGRATION=1` and require `.env.probe` (gitignored — local only):

```bash
INTEGRATION=1 pytest backend/tests/integration -v
```

The default `pytest backend/tests` run skips them.

### Other conventions

- Per-feature route modules live in `backend/plugtrack/api/routes/` and are registered in `create_app()`.
- Models: explicit `__tablename__`, explicit `nullable=`, `datetime.now(timezone.utc)` for default timestamps, `__repr__` for debugging.
- Use `HTTPException(status_code=…, detail=…)` for client-facing errors; never surface raw exceptions.
- Never query without a `user_id` filter. Never bypass `Settings.get_setting` with hard-coded constants for user-tunable values.
- Encrypted columns (`Car.vin_encrypted`) are accessed via property setters/getters in the model — call sites read/write plaintext.
- Tests must NEVER touch a real database; the `test_engine` / `test_sessionmaker` fixtures in `backend/tests/conftest.py` give each test its own SQLite file in `tmp_path`.

## Reference Docs in This Repo

- [`README.md`](README.md) — public-facing intro, quickstart, architecture overview.
- [`backend/CONTRIBUTING.md`](backend/CONTRIBUTING.md) — backend contributor notes.
- `.env.example` — required environment variables (`APP_SECRET_KEY`, optional `DATABASE_URL`, `COOKIE_SECURE`).
- `compose.yaml` — production two-service compose stack pulling from GHCR.
- `compose-dev.yaml` — source-build compose stack used by the deploy scripts.
