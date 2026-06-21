# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

PlugTrack is an EV charge-tracking app. Its **primary data source is charge screenshots sent to a Telegram bot**, which an OpenAI vision model extracts into charging sessions; it also serves a React dashboard and an MCP server for agentic access. (Throughout this doc, "v2" refers to the current FastAPI + React **codebase generation** — v1 was the legacy Flask app — not the product release version, which is 3.x.)

It is a two-service container app:

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

> Gotcha: CI typechecks with `tsc -b`, which is **stricter** than `npm run typecheck` (`tsc --noEmit`) — notably it enforces `noUncheckedIndexedAccess`. Run `npx tsc -b` locally before pushing if `typecheck` passes but CI fails.

### CLI scripts (run in-container)

```bash
# Run inside the api container.
python -m plugtrack.scripts.import_mycupra_csv <file.csv>   # backfill sessions from a MyCupra export (dry-run by default, idempotent)
python -m plugtrack.scripts.backfill_curves                 # match + attach power curves to existing sessions (idempotent — dedupe skips)
python -m plugtrack.scripts.seed_demo                       # seed demo data
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
4. Wires long-lived services into `app.state`:
   - `telegram_manager` — owns the Telegram ingest bot long-poll task; reconciles it against DB settings (stays off until `telegram_bot_enabled`).
   - `scheduler` — one `AsyncIOScheduler` running the hourly `run_digest_tick` job (weekly/monthly digests) plus a conditional backup job. Exposed under the legacy alias `backup_scheduler` too.
   - the MCP session manager — started for the `/mcp` streamable-HTTP sub-app mounted in `create_app()`.

Routes are registered at the bottom of `create_app()`; every blueprint must be added there, never on import. The `EXEMPT_PATHS` sets in `api/auth_middleware.py` and `security/csrf.py` gate which paths bypass auth/CSRF — see "EXEMPT_PATHS pinning" below.

### Layered data flow
`Route → Service (async functions / dataclasses) → Model → SQLAlchemy`. Routes stay thin; business logic lives in `backend/plugtrack/services/`. **Always filter queries by `request.state.user_id`** — multi-user isolation is enforced at the query level, not by the database.

Key services:

- The ingestion pipeline (Telegram screenshot → session): `services/telegram_manager.py` (owns the bot task) → `services/telegram_ingest.py` (photo/callback handlers) → `services/screenshot_extraction.py` (OpenAI vision → structured record) → `services/screenshot_correlation.py` (merge per-screenshot extractions into one session) → `services/screenshot_commit.py` (persist `ChargingSession`, dedupe) → `services/ingest_location.py` (geocode place name at commit).
- `services/bot_agent.py` — agentic tool-calling loop for the Telegram bot; dispatches to the in-process MCP tool core (`mcp/tools.py`), user-scoped (two-phase propose/commit).
- `services/cost.py` — single source of truth for cost computation (see "Cost precedence" below).
- `services/location_clustering.py`, `services/geocoding.py` — auto-cluster plug-in coords into per-user `Location` rows; reverse-geocode addresses on first sighting.
- `services/dashboard_service.py` — single AsyncSession aggregation pass for the v1 dashboard (cars panel + recent sessions + lifetime totals + top locations).
- `services/auth_service.py` — bootstrap + login + password hashing.

### Frontend
React 19 + zustand stores (`frontend/src/stores/` — currently `authStore` and `settingsStore`). Pages in `frontend/src/pages/`, shared components in `frontend/src/components/`, the typed API client in `frontend/src/api/client.ts`. Tailwind 4 (no preprocessor); dark mode via `theme.ts` applied to `<html>`. Vitest + Testing Library for tests.

JSON endpoints follow a flat shape — keep new APIs consistent with what `client.ts` exposes.

### MCP + agentic bot
The MCP **tool core** lives in `mcp/tools.py` and is the single implementation of the agentic operations (two-phase propose/commit — a `propose_*` call returns a proposal that the caller confirms before a `commit`). Two front-ends share it: the agentic Telegram bot (`services/bot_agent.py`, in-process, user-scoped) and the external **FastMCP server** mounted at `/mcp` with its own bearer-token auth and scopes (which is why `/mcp` is in `EXEMPT_PATHS` — the session-cookie + CSRF middlewares skip it). External MCP clients (e.g. Claude Desktop) must point at the **trailing-slash** URL `/mcp/`.

## Conventions to Follow

### Multi-worker tripwire
Backend MUST run with `WEB_CONCURRENCY=1` (or unset). The lifespan handler asserts this AND acquires a filesystem lock at `/tmp/plugtrack.lock` so direct `--workers N` invocations also fail — only the first worker gets the lock, the rest crash. This is non-negotiable: SQLite + the in-process APScheduler are not multi-worker safe.

### Schema changes (no Alembic)
There is **no migration framework**. `Base.metadata.create_all` (run in the lifespan) only creates *missing tables* — it never adds columns to an existing table. To add a column to a live table you MUST append it to the `additions` tuple in `main.py:_apply_additive_migrations`, which runs idempotent `ALTER TABLE … ADD COLUMN` (PRAGMA-guarded, so re-runs are no-ops). Adding the field to the model alone will pass tests (fresh DB per test) but silently break prod, where the table already exists.

### Distance storage rule
All distance columns are stored in **kilometres** with a `_km` suffix (`odometer_at_session_km`, `radius_m` is the metres exception used for the clustering radius only). UI converts to the user's display unit via the `distance_unit` setting (default `mi`) using `formatDistance()` from `frontend/src/stores/settingsStore.ts`. Odometer/range values come from screenshot extraction or manual entry and are stored in km, so no conversion happens server-side.

### Cost precedence
The cost-precedence rule is implemented exactly once in `backend/plugtrack/services/cost.py:compute_session_cost`. Order of resolution:

1. `total_cost_pence_override` → `cost_basis = "override_total"`
2. `cost_per_kwh_override_p` → `"override_per_kwh"`
3. Location with `is_free=True` → `"location_free"` (cost_pence = 0)
4. Location with `default_cost_per_kwh_p` → `"location_rate"`
5. Settings `default_home_rate_p_per_kwh` → `"home_rate"`
6. Otherwise → `"unknown"` (cost_pence = NULL)

User overrides are sacred — re-ingestion (duplicate screenshots) and CSV re-imports MUST NOT overwrite them. See spec §3.3 for the full rationale.

### EXEMPT_PATHS pinning
`backend/tests/api/test_security_invariants.py` pins a SHA-256 of the union of `EXEMPT_PATHS` from both the auth and CSRF middlewares. Extending either set requires:

1. Updating the path lists in their respective middleware modules.
2. Regenerating the hardcoded `EXPECTED_EXEMPT_HASH` constant in the invariants test.
3. **Explicit user sign-off** — the comment block in the test calls this out as a manual-review step.

The test runs in the default suite, so a drift will fail CI immediately.

### Integration test gate
`backend/tests/integration/` is reserved for tests that exercise real network paths, gated behind `INTEGRATION=1`. It is currently empty (the former real-account pycupra probe was removed in the standalone pivot):

```bash
INTEGRATION=1 pytest backend/tests/integration -v
```

The default `pytest backend/tests` run skips this directory.

### Other conventions

- Per-feature route modules live in `backend/plugtrack/api/routes/` and are registered in `create_app()`.
- Models: explicit `__tablename__`, explicit `nullable=`, `datetime.now(timezone.utc)` for default timestamps, `__repr__` for debugging.
- Use `HTTPException(status_code=…, detail=…)` for client-facing errors; never surface raw exceptions.
- Never query without a `user_id` filter. Never bypass `Settings.get_setting` with hard-coded constants for user-tunable values.
- Encrypted columns (`Car.vin_encrypted`) are accessed via property setters/getters in the model — call sites read/write plaintext. Secret **settings** rows (`telegram_bot_token`, `openai_api_key`) are likewise Fernet-encrypted at rest via `security/crypto` (keyed on `APP_SECRET_KEY`); decrypt at point of use, never log or compare them raw.
- Tests must NEVER touch a real database; the `test_engine` / `test_sessionmaker` fixtures in `backend/tests/conftest.py` give each test its own SQLite file in `tmp_path`.

## Reference Docs in This Repo

- [`README.md`](README.md) — public-facing intro, quickstart, architecture overview.
- [`backend/CONTRIBUTING.md`](backend/CONTRIBUTING.md) — backend contributor notes.
- `.env.example` — required environment variables (`APP_SECRET_KEY`, optional `DATABASE_URL`, `COOKIE_SECURE`).
- `compose.yaml` — production two-service compose stack pulling from GHCR.
- `compose-dev.yaml` — source-build compose stack used by the deploy scripts.
