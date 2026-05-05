# PlugTrack

PlugTrack v2 is a self-hosted, container-native EV charging tracker. A FastAPI backend pulls telematics from the official **My Cupra** cloud (via [pycupra](https://pypi.org/project/pycupra/)), synthesises charging sessions from the SoC stream, and serves them to a React 19 single-page app. There is no manual logging step — plug the car in, and a session appears once it finishes charging.

It is built around four ideas:

- **Telematics-first.** A state machine consumes the polled SoC + charging-status stream and emits one `ChargingSession` per plug-in cycle. No CSV imports, no scraping, no manual data entry (though manual entry is supported as a fallback).
- **Cost is sacred.** Per-kWh / total-cost overrides set by the user are never overwritten by re-syncs. A strict precedence rule (`override_total` → `override_per_kwh` → `location_free` → `location_rate` → `home_rate` → `unknown`) is implemented exactly once in `services/cost.py`.
- **Locations cluster themselves.** Plug-in coordinates are clustered into per-user `Location` rows with reverse-geocoded addresses; labelling a location retro-recomputes the costs of past sessions that resolved against it.
- **Single-user, single-worker.** SQLite + an in-process APScheduler. Multi-worker is hard-blocked at startup. This keeps the operational surface tiny.

## Screenshots

The dashboard answers "what is the car doing right now?" in one glance — a hero per-car card with a live charging progress bar, a 30-day spend chart, lifetime KPIs, recent sessions, and top locations. Session detail is built around the live charge curve. Locations is a real OpenStreetMap-tiled map with cost-banded markers (green = free, cyan = ~home rate, amber = expensive, red = very expensive).

## Quickstart — pull images from GHCR

This is the easiest path. You need `docker` (with `compose`) and a way to generate a random secret. No source code, no build toolchain, no Python.

```bash
# 1. Grab the compose file (or write it yourself — see compose.yaml in this repo)
curl -O https://raw.githubusercontent.com/MrSiJo/PlugTrack/main/compose.yaml

# 2. Generate a strong secret (≥32 chars; the loader rejects shorter ones)
echo "APP_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" > .env

# 3. Pull and start
docker compose pull
docker compose up -d
```

Open http://localhost:9279 in a browser. First-run setup prompts you to create the single administrator account. After that:

- Add your Cupra Connect credentials in **Settings → Cupra Connect** to start syncing.
- Add a car in **Cars** (or use **Discover from Cupra** to pull one off your account).
- Sit back. Plug in. A session will appear on the dashboard once charging completes.

### Pinning a specific image tag

`compose.yaml` defaults to `:latest`. To pin a release:

```bash
echo "PLUGTRACK_TAG=v2.1.0" >> .env
docker compose pull && docker compose up -d
```

Available tags live on the GHCR package pages:

- https://github.com/MrSiJo/PlugTrack/pkgs/container/plugtrack-api
- https://github.com/MrSiJo/PlugTrack/pkgs/container/plugtrack-ui

Or check https://github.com/MrSiJo/PlugTrack/releases for the matching changelog.

Tags published by CI:

| Trigger                                | Tags produced                                       |
| -------------------------------------- | --------------------------------------------------- |
| push to `main`                         | `latest`, `sha-<short>`                             |
| release-please PR merged (cuts a tag)  | `vX.Y.Z`, `X.Y`, `X`, `latest`                      |
| pull request                           | (build-only, no push)                               |

Both images are multi-arch (`linux/amd64` + `linux/arm64`).

## Quickstart — local dev (run from source)

For day-to-day development on the backend or frontend.

### 1. Clone and configure

```bash
git clone https://github.com/MrSiJo/PlugTrack.git
cd PlugTrack
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))" >> .env  # paste as APP_SECRET_KEY
```

### 2. Backend — factory mode is required so the lifespan handler runs

```bash
cd backend
pip install -r requirements.txt
uvicorn plugtrack.main:create_app --factory --port 9278 --reload
```

### 3. Frontend — Vite proxies `/api` to `localhost:9278`

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

### 4. Tests

```bash
# Backend (default suite — integration tests are gated)
cd backend && pytest tests

# Frontend
cd frontend && npm test -- --run && npm run typecheck && npm run lint
```

## Self-hosting from source (build locally, push to a remote Docker host)

If you don't want to use the published images — say, you've patched the source — `scripts/deploy.{ps1,sh}` builds both images locally via `compose-dev.yaml` and runs `docker compose up -d` against your active Docker context. The scripts refuse to run if your context is `default`, guarding against accidentally deploying to the developer machine.

```bash
docker context use <your-remote-context>
scripts/deploy.ps1     # PowerShell on Windows
# or
scripts/deploy.sh      # bash on Linux / macOS / WSL
```

## Configuration

All configuration lives in two places.

### `.env` — boot-time secrets

| Variable                   | Required                       | Default              | Notes                                                |
| -------------------------- | ------------------------------ | -------------------- | ---------------------------------------------------- |
| `APP_SECRET_KEY`           | yes                            | —                    | ≥32 chars, used to sign cookies + encrypt VINs       |
| `DATABASE_URL`             | no                             | `sqlite+aiosqlite:///./data/plugtrack.db` | Override only if you want non-default DB path |
| `COOKIE_SECURE`            | no                             | `true`               | Set to `false` for plain-HTTP local dev              |
| `WEB_CONCURRENCY`          | no                             | `1` (enforced)       | **Must be `1`.** The lifespan handler asserts this and acquires a filesystem lock so direct `--workers N` invocations also fail. |
| `PYCUPRA_IMAGE_DIR`        | no                             | `./www/pycupra`      | Where the API reads cached vehicle images from. Set automatically inside the container. |
| `PLUGTRACK_TAG`            | only for `compose.yaml`        | `latest`             | Image tag to pull from GHCR.                         |

### Settings catalogue (UI) — runtime tunables

After first-run setup, all per-user configuration is in **Settings**:

- **Display:** theme (light/dark/system), distance unit (mi/km), currency.
- **Cupra Connect:** username / password / S-PIN. Encrypted at rest.
- **Charging defaults:** default home rate (p/kWh), petrol price (p/L), petrol MPG (used for the petrol comparison).
- **Sync:** active/idle poll cadences and the cap on simultaneous syncs.

Cupra credentials are encrypted with `APP_SECRET_KEY` — rotating that secret renders saved credentials unreadable, so plan accordingly.

## Architecture

PlugTrack is two services on a shared bridge network:

```
┌─────────────────┐  /api/*  ┌────────────────────────────────┐
│ plugtrack-ui    │ ───────► │ plugtrack-api                  │
│ nginx + SPA     │          │ FastAPI · async SQLAlchemy 2.x │
│ port 80 → :9279 │          │ APScheduler · pycupra adapter  │
│                 │          │ port 9278                      │
└─────────────────┘          └─────────────┬──────────────────┘
                                           │
                                           ▼
                                    SQLite + APScheduler
                                    (single-worker, in-process)
```

### Backend

`backend/plugtrack/main.py:create_app()` is the single source of truth for app wiring. The lifespan handler:

1. Asserts `WEB_CONCURRENCY=1` and acquires `/tmp/plugtrack.lock` so direct `--workers N` invocations crash on the first non-zero worker.
2. Creates the schema (`Base.metadata.create_all`).
3. Seeds defaults into the `setting` catalogue.
4. Wires three long-lived services into `app.state`:
   - `event_bus` — pub/sub fan-out for SSE clients.
   - `sync_orchestrator` — per-car mutex + state cache.
   - `sync_scheduler` — APScheduler-backed adaptive cadence (faster polls while charging, backs off when idle / on auth failure).

Key services live under `backend/plugtrack/services/`:

| Service                        | Purpose                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `sync_orchestrator.py`         | Per-car mutex + live state cache.                                       |
| `sync_scheduler.py`            | APScheduler-backed adaptive poll cadence.                               |
| `sync_worker.py`               | Reads pycupra adapter, runs the state machine, persists sessions.       |
| `session_synthesiser.py`       | Pure state-machine: SoC + charging-status stream → one ChargingSession. |
| `cost.py`                      | Single source of truth for cost computation (precedence rule).          |
| `location_clustering.py`       | Auto-clusters plug-in coords into per-user `Location` rows.             |
| `geocoding.py`                 | Reverse-geocodes addresses on first sighting.                           |
| `dashboard_service.py`         | Single AsyncSession aggregation pass for the dashboard.                 |
| `dashboard_trend.py`           | Daily spend totals (powers the dashboard chart).                        |
| `event_bus.py`                 | `EventBus.publish(event)` / `subscribe(job_id)` pair backing SSE.       |

Routes are thin and live under `backend/plugtrack/api/routes/`. **Every query filters by `request.state.user_id`** — multi-user isolation is enforced at the query level, not by the database.

### Frontend

React 19 + Vite + Tailwind v4 + zustand. One zustand store per domain (`auth`, `settings`, `sync`, `cars`, `sessions`). Pages in `frontend/src/pages/`, shared primitives in `frontend/src/components/ui/`, the typed API client in `frontend/src/api/client.ts`. Distance values flow through `formatDistance(km)` against the user's chosen unit; cost values flow through `formatCurrency(pence, currency)` against the active currency setting.

Visual identity:

- "Electric" palette: green → cyan → blue gradient on charcoal-navy backgrounds.
- Inter typography (self-hosted, offline-capable) with tabular numerals.
- shadcn/ui primitives + Recharts for the dashboard spend chart + Leaflet (OSM/CartoDB tiles) for the locations map.
- ⌘K command palette for navigation and theme toggle.

## Storage layout

Run with the default `compose.yaml` (named volumes, managed by Docker):

| Volume               | Mounted at  | Contents                                                       |
| -------------------- | ----------- | -------------------------------------------------------------- |
| `plugtrack-data`     | `/app/data` | SQLite DB, pycupra token cache.                                |
| `plugtrack-logs`     | `/app/logs` | App logs.                                                      |
| `plugtrack-www`      | `/app/www`  | pycupra-fetched per-VIN car images served by `/api/cars/:id/image`. |

Run with `compose-dev.yaml` and the same paths bind to `/dockerdata/plugtrack/{data,logs,www}` on the host instead — easier to inspect, less portable.

## Container images and CI

Images are published to the GitHub Container Registry:

- `ghcr.io/mrsijo/plugtrack-api`
- `ghcr.io/mrsijo/plugtrack-ui`

Both images are built for `linux/amd64` and `linux/arm64` (Raspberry Pi 4/5 and Apple Silicon work).

Two workflows drive publishing:

- `.github/workflows/build-images.yml` — every push to `main` produces `:latest` + `:sha-<short>`.
- `.github/workflows/release-please.yml` — automates semantic-versioned releases (see below).

### Versioned releases — automated via release-please

Versioning follows [Conventional Commits](https://www.conventionalcommits.org/) and is fully automated:

1. Push commits to `main` with prefixes like `feat:`, `fix:`, `feat!:` (breaking), or `chore:`/`docs:`/`ci:` (no version bump).
2. [release-please](https://github.com/googleapis/release-please) maintains a `chore(main): release X.Y.Z` PR that accumulates everything since the last release, with an auto-generated `CHANGELOG.md` and the proposed version (`feat:` → minor, `fix:` → patch, `feat!:` → major).
3. **Merging that PR** cuts the `vX.Y.Z` git tag, creates the matching GitHub Release, and triggers the multi-arch image build, pushing `:vX.Y.Z`, `:X.Y`, `:X`, and `:latest` to GHCR.

State is tracked in `.release-please-manifest.json`. To skip a release for a window (e.g. several "wip" `feat:` commits that aren't ready), simply don't merge the Release PR — it will keep accumulating until you do.

## Out of scope (for now)

The undocumented Cariad `multicharge` BFF used by the My Cupra mobile app for full charging history is **not** shipped here. That endpoint is officially internal, would tie us to a single OEM tenancy, and pycupra does not cover it. The plugin contract `ChargingHistoryProvider` exists in `backend/plugtrack/plugins/` for any future personal-plugin implementation; nothing in mainline depends on it being installed.

## Project layout

```
.
├── .github/workflows/build-images.yml   # CI: build + push GHCR images
├── backend/                             # FastAPI app
│   ├── plugtrack/
│   │   ├── api/                         # routes + middleware
│   │   ├── models/                      # SQLAlchemy models
│   │   ├── plugins/                     # pycupra adapter + plugin contract
│   │   ├── services/                    # business logic
│   │   └── main.py                      # create_app() — single source of truth
│   └── tests/                           # pytest (default + integration suites)
├── frontend/                            # React 19 SPA
│   └── src/
│       ├── api/                         # typed client
│       ├── components/ui/               # shadcn + project primitives
│       ├── pages/                       # one component per route
│       └── stores/                      # zustand
├── compose.yaml                         # GHCR pull (default)
├── compose-dev.yaml                     # source-build (used by scripts/deploy.*)
└── scripts/deploy.{ps1,sh}              # source-build deploy entry points
```

## Reference

- Project conventions for Claude Code: [`CLAUDE.md`](CLAUDE.md)
- Backend contributor notes: [`backend/CONTRIBUTING.md`](backend/CONTRIBUTING.md)

## Licence

See [`LICENSE`](LICENSE).
