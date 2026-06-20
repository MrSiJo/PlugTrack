# PlugTrack

PlugTrack is a self-hosted, container-native EV charging tracker. You charge, screenshot the charging app — Tesla, Osprey, Electroverse, My Cupra, a home granny charger, anything — and send it to a **Telegram bot**. An OpenAI vision model reads the energy, cost, location, SoC and times off the image, merges multiple screenshots of the same charge into one session, and you confirm it with a single tap. A FastAPI backend persists the sessions and serves them to a React 19 single-page app.

> **History — telematics is gone.** PlugTrack began by pulling data straight from the My Cupra cloud via [pycupra](https://pypi.org/project/pycupra/). In June 2026 the VW Group gated that third-party API behind Firebase **App Check / Play Integrity** — a device-bound attestation that can't be satisfied headlessly — so the telematics path stopped working. As of **v3.0** it has been **fully removed**. Screenshot ingestion is now PlugTrack's sole, **OEM-agnostic** input: because it reads screenshots, it works with any charging network's app, not one manufacturer's API.

It is built around four ideas:

- **Screenshot-first, app-agnostic.** Send the screenshots you already take to a Telegram bot; an OpenAI vision model (a `gpt-5`-class model, swappable) extracts the fields, and a deterministic correlator merges the network screenshot (kWh + cost + location) with the My Cupra screenshot (SoC + curve) into one `ChargingSession`. Free-text notes and photo captions work too. Manual entry remains as a fallback.
- **Cost is sacred.** Per-kWh / total-cost overrides set by the user are never overwritten. A strict precedence rule (`override_total` → `override_per_kwh` → `location_free` → `location_rate` → `home_rate` → `unknown`) is implemented exactly once in `services/cost.py`. Editing a session re-rates it at its frozen tariff; labelling a location retro-recomputes the costs of past sessions that resolved against it.
- **Locations build themselves.** Imported charges are forward-geocoded from their address and clustered into per-user `Location` rows with clean `<Network> <Place>` names (e.g. "Tesla Lifton", "Osprey Land's End"). Per-location rates and a free flag feed straight into the cost precedence chain.
- **Single-user, single-worker.** SQLite + an in-process APScheduler. Multi-worker is hard-blocked at startup. This keeps the operational surface tiny.

## Features

**Telegram ingestion (primary input)**

- Send one or more screenshots of a finished charge from any app; an OpenAI vision model extracts energy, cost, per-kWh, start/end times, SoC, location, network and the charge-power curve.
- Multiple screenshots of the same charge (e.g. the network app *and* My Cupra) auto-merge by overlapping time window into a single session — the model is **"Save = one charge"**.
- A photo **caption** ("home") or a **free-text note** (`home 9.3kwh 8h31m`) is parsed by the same model — no rigid syntax.
- **Home / granny-charger** charges: the metered *delivered* kWh is billed truth; SoC-banked energy and the AC→DC efficiency surface for free.
- An inline **confirm card** shows projected kWh + cost (including the home/location rate) and edits itself in place as more screenshots merge; one tap to Save or Discard. A duplicate-screenshot guard means re-sending a saved charge never double-counts.

**Conversational agent** — the bot is agentic. Beyond ingesting screenshots it can answer questions and make edits in plain language ("spend this month?", "how much on rapids?", "label that last charge as Home", "update session 42 from the next screenshot"). All actions go through a two-phase **propose → confirm → commit** flow, and every answer is grounded in a server-computed stats snapshot, so the model only restates real figures — it never invents numbers.

**Mileage via text** — include an odometer in a message or caption (`home 12345mi 9.3kwh 8h31m`); it lands on the session and updates current mileage and annual mileage tracking (both derived from session odometers).

**Charging sessions** — full CRUD with a rich detail page built around the **charge-power curve** (AC and DC), plus duration, average/peak power, range added, cost-per-mile and a petrol-cost comparison. Sources are tagged (`telegram`, `manual`, `import`).

**MyCupra CSV backfill** — a one-off importer (`python -m plugtrack.scripts.import_mycupra_csv`, dry-run by default, idempotent) seeds historical sessions from a My Cupra "charging statistics" export, including real energy-transfer time (`actual_charge_seconds`) distinct from the plug-in window.

**Insights** — five analytics modules over your history: spend/energy **over time**, **home vs public** split, **network** breakdown, **efficiency** trend, and per-car **mileage-allowance pacing** (are you on track for your annual target). Plus a per-location breakdown with average p/kWh.

**Planner** — estimate a home charge: pick a car and a start/target SoC and get the duration, finish time, cost, and whether it fits one overnight window — based on the median power of your recent home charges.

**Dashboard & analytics** — a per-car hero card showing last-known battery (after your most recent charge) and a summary of that charge, a 30-day spend chart, lifetime KPIs, recent sessions, and top locations. A locations map (OpenStreetMap) shows cost-banded markers.

**Admin** — one page for everything operational: integration setup (Telegram, OpenAI, geocoding), display/cost/charging preferences, locations & cars management, scheduled **backups** + on-demand **CSV/JSON export**, and **MCP API tokens**.

**MCP server** — a FastMCP streamable-HTTP server at `/mcp/` exposes the same tool core (find/read charges, insights, and two-phase mutations) to any MCP client over bearer-token auth with read / readwrite scopes. Mint and revoke tokens from the Admin page.

**Bot health** — `/test` returns a health report (token + key validity, config completeness) straight to the chat.

## Screenshots

The dashboard answers "where's my battery and what did I last spend?" in one glance — a hero per-car card, a 30-day spend chart, lifetime KPIs, recent sessions, and top locations. Session detail is built around the charge-power curve. Locations is a real OpenStreetMap-tiled map with cost-banded markers (green = free, cyan = ~home rate, amber = expensive, red = very expensive).

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

- Add a car in **Admin → Cars** (make, model, battery size, efficiency).
- In **Admin → Integrations**, paste your Telegram bot token and OpenAI API key (both encrypted at rest), set your allowed Telegram user id + default car, and enable the bot and AI.
- Message your bot a charge screenshot, confirm the card, and the session appears on the dashboard.

### Pinning a specific image tag

`compose.yaml` defaults to `:latest`. To pin a release:

```bash
echo "PLUGTRACK_TAG=3.0.0" >> .env
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
| release-please PR merged (cuts a tag)  | `X.Y.Z`, `X.Y`, `X`, `latest`                       |
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
| `APP_SECRET_KEY`           | yes                            | —                    | ≥32 chars, used to sign cookies + encrypt secrets/VINs |
| `DATABASE_URL`             | no                             | `sqlite+aiosqlite:///./data/plugtrack.db` | Override only if you want a non-default DB path |
| `COOKIE_SECURE`            | no                             | `true`               | Set to `false` for plain-HTTP local dev              |
| `WEB_CONCURRENCY`          | no                             | `1` (enforced)       | **Must be `1`.** The lifespan handler asserts this and acquires a filesystem lock so direct `--workers N` invocations also fail. |
| `PLUGTRACK_TAG`            | only for `compose.yaml`        | `latest`             | Image tag to pull from GHCR.                         |

### Settings catalogue (UI) — runtime tunables

After first-run setup, all per-user configuration is in **Admin**:

- **Display:** theme (light/dark/system), distance unit (mi/km), currency.
- **Integrations — Telegram & AI:** Telegram bot token, allowed Telegram user id(s), default car, OpenAI API key + model, optional input/output token prices (for cost accounting). The bot runs as a lifespan background task, gated by `telegram_bot_enabled` / `ai_enabled`, and reconciles live when you change its settings — no redeploy.
- **Integrations — Geocoding:** provider (`nominatim` default — free and keyless), optional API key for Mapbox / OpenCage, cluster radius.
- **Charging defaults:** default home rate (p/kWh), home-charge window, fallback power (kW), petrol price (p/L), petrol MPG (used for the petrol comparison).
- **Backup:** enable scheduled snapshots, interval, retention count.

Secrets (Telegram token, OpenAI key) are encrypted at rest with `APP_SECRET_KEY` — rotating that secret renders them unreadable, so plan accordingly.

## Architecture

PlugTrack is two services on a shared bridge network:

```
   Telegram  ──photos/text──►  ┌────────────────────────────────┐
   (your phone)                │ plugtrack-api                  │
                               │ FastAPI · async SQLAlchemy 2.x │
┌─────────────────┐  /api/*    │ Telegram long-poll bot         │
│ plugtrack-ui    │ ─────────► │ OpenAI vision extraction       │
│ nginx + SPA     │            │ MCP server · APScheduler       │
│ port 80 → :9279 │            │ port 9278                      │
└─────────────────┘            └─────────────┬──────────────────┘
                                             │            ▲
                                             ▼            └─ OpenAI API / Nominatim
                                      SQLite + APScheduler
                                      (single-worker, in-process)
```

The bot long-polls Telegram (no inbound webhook needed), sends images to the OpenAI Responses API for extraction, forward-geocodes new locations via Nominatim, and persists confirmed sessions to the same SQLite database the dashboard reads.

### Backend

`backend/plugtrack/main.py:create_app()` is the single source of truth for app wiring. The lifespan handler:

1. Asserts `WEB_CONCURRENCY=1` and acquires `/tmp/plugtrack.lock` so direct `--workers N` invocations crash on the first non-zero worker.
2. Creates the schema (`Base.metadata.create_all`) and applies additive migrations.
3. Seeds defaults into the `setting` catalogue.
4. Starts the long-lived background services: the **Telegram bot manager**, the **MCP session manager**, and the **APScheduler backup job**.

Key services live under `backend/plugtrack/services/`:

| Service                        | Purpose                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `telegram_ingest.py` / `telegram_manager.py` | Long-poll bot: routes photos/captions/text → stage → confirm card → commit; agentic tool loop; `/test` health. |
| `screenshot_extraction.py`     | OpenAI vision/text extraction → structured `Extraction` (energy, cost, SoC, location, odometer, curve, `<Network> <Place>` short name). |
| `screenshot_correlation.py`    | Merges a Save-batch of extractions into one `MergedSession` per charge by overlapping time window. |
| `screenshot_commit.py`         | Persists a `MergedSession` as a `ChargingSession` (cost, kWh, location resolution); duplicate guard. |
| `ingest_location.py`           | Forward-geocodes an import's address → links/creates a named `Location`. |
| `cost.py`                      | Single source of truth for cost computation (precedence rule + edit-time re-rating). |
| `location_clustering.py` / `geocoding.py` | Clusters coordinates into per-user `Location` rows; forward/reverse geocoding providers. |
| `mileage_tracking.py`          | Annual mileage periods; current mileage derived from session odometers. |
| `dashboard_service.py` / `dashboard_trend.py` | Aggregation passes for the dashboard + daily spend chart.   |
| `insights_stats.py` / `usage_stats.py` | Numeric aggregators behind the Insights page and the bot's grounded answers. |
| `charge_planner.py`            | Home-charge duration/cost estimate from recent home-charge power.        |
| `backup.py`                    | VACUUM-INTO rotating SQLite snapshots with keep-last-N pruning.           |
| `mcp/` (`server.py`, `tools.py`) | FastMCP server + the user-scoped, two-phase propose/commit tool core (shared by the bot and external MCP clients). |

Routes are thin and live under `backend/plugtrack/api/routes/`. **Every query filters by `request.state.user_id`** — multi-user isolation is enforced at the query level, not by the database. Passwords are hashed with Argon2; mutating routes are CSRF-protected and login is rate-limited.

### Frontend

React 19 + Vite + Tailwind v4 + zustand. Zustand stores per domain (`auth`, `settings`); other domains are fetched through the typed API client on demand. Pages in `frontend/src/pages/`, shared primitives in `frontend/src/components/ui/`, the client in `frontend/src/api/client.ts`. Distance values flow through `formatDistance(km)` against the user's chosen unit; cost values through `formatCurrency(pence, currency)`.

Visual identity:

- "Electric" palette: green → cyan → blue gradient on charcoal-navy backgrounds.
- Inter typography (self-hosted, offline-capable) with tabular numerals.
- shadcn/ui primitives + Recharts for the spend chart + Leaflet (OSM/CartoDB tiles) for the locations map.
- ⌘K command palette for navigation and theme toggle.

## Storage layout

Run with the default `compose.yaml` (named volumes, managed by Docker):

| Volume               | Mounted at  | Contents                                                       |
| -------------------- | ----------- | -------------------------------------------------------------- |
| `plugtrack-data`     | `/app/data` | SQLite DB + rotating backup snapshots (`/app/data/backups`).   |
| `plugtrack-logs`     | `/app/logs` | App logs.                                                      |
| `plugtrack-www`      | `/app/www`  | Cached per-VIN car images served by `/api/cars/:id/image` (no longer auto-refreshed since telematics was removed; any previously cached image still displays). |

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
3. **Merging that PR** cuts the `vX.Y.Z` git tag, creates the matching GitHub Release, and (via a dispatch from `release-please.yml`) runs the multi-arch image build, pushing `:X.Y.Z`, `:X.Y`, `:X`, and `:latest` to GHCR. (The image tags drop the leading `v`; the dispatch is explicit because a `GITHUB_TOKEN`-created tag can't trigger another workflow.)

State is tracked in `.release-please-manifest.json`. To skip a release for a window, simply don't merge the Release PR — it will keep accumulating until you do.

## Project layout

```
.
├── .github/workflows/build-images.yml   # CI: build + push GHCR images
├── backend/                             # FastAPI app
│   ├── plugtrack/
│   │   ├── api/                         # routes + middleware
│   │   ├── mcp/                         # FastMCP server + tool core
│   │   ├── models/                      # SQLAlchemy models
│   │   ├── services/                    # business logic
│   │   ├── scripts/                     # CLI helpers (e.g. MyCupra CSV import)
│   │   └── main.py                      # create_app() — single source of truth
│   └── tests/                           # pytest (default + integration suites)
├── frontend/                            # React 19 SPA
│   └── src/
│       ├── api/                         # typed client
│       ├── components/                  # shadcn + project primitives
│       ├── pages/                       # one component per route
│       └── stores/                      # zustand (auth, settings)
├── compose.yaml                         # GHCR pull (default)
├── compose-dev.yaml                     # source-build (used by scripts/deploy.*)
└── scripts/deploy.{ps1,sh}              # source-build deploy entry points
```

## Reference

- Project conventions for Claude Code: [`CLAUDE.md`](CLAUDE.md)
- Backend contributor notes: [`backend/CONTRIBUTING.md`](backend/CONTRIBUTING.md)

## Licence

See [`LICENSE`](LICENSE).
