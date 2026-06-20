# PlugTrack architecture

PlugTrack is two services on a shared bridge network. For installation and configuration see [`INSTALL.md`](INSTALL.md).

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

## Design principles

- **Screenshot-first, app-agnostic.** Send the screenshots you already take to a Telegram bot; an OpenAI vision model (a `gpt-5`-class model, swappable) extracts the fields, and a deterministic correlator merges the network screenshot (kWh + cost + location) with the My Cupra screenshot (SoC + curve) into one `ChargingSession`. Free-text notes and photo captions work too. Manual entry remains as a fallback.
- **Cost is sacred.** Per-kWh / total-cost overrides set by the user are never overwritten. A strict precedence rule (`override_total` → `override_per_kwh` → `location_free` → `location_rate` → `home_rate` → `unknown`) is implemented exactly once in `services/cost.py`. Editing a session re-rates it at its frozen tariff; labelling a location retro-recomputes the costs of past sessions that resolved against it.
- **Locations build themselves.** Imported charges are forward-geocoded from their address and clustered into per-user `Location` rows with clean `<Network> <Place>` names (e.g. "Tesla Lifton", "Osprey Land's End"). Per-location rates and a free flag feed straight into the cost precedence chain.
- **Single-user, single-worker.** SQLite + an in-process APScheduler. Multi-worker is hard-blocked at startup. This keeps the operational surface tiny.

## Backend

`backend/plugtrack/main.py:create_app()` is the single source of truth for app wiring. The lifespan handler:

1. Asserts `WEB_CONCURRENCY=1` and acquires `/tmp/plugtrack.lock` so direct `--workers N` invocations crash on the first non-zero worker.
2. Creates the schema (`Base.metadata.create_all`) and applies additive migrations.
3. Seeds defaults into the `setting` catalogue.
4. Starts the long-lived background services: the **Telegram bot manager**, the **MCP session manager**, and an **APScheduler** hosting the rotating-backup job and the hourly proactive-digest tick.

Key services live under `backend/plugtrack/services/`:

| Service                        | Purpose                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `telegram_ingest.py` / `telegram_manager.py` | Long-poll bot: routes photos/captions/text → stage → confirm card → commit; per-charge car resolution; agentic tool loop; `/test` health. |
| `screenshot_extraction.py`     | OpenAI vision/text extraction → structured `Extraction` (energy, cost, SoC, location, odometer, curve, `<Network> <Place>` short name). |
| `screenshot_correlation.py`    | Merges a Save-batch of extractions into one `MergedSession` per charge by overlapping time window. |
| `screenshot_commit.py`         | Persists a `MergedSession` as a `ChargingSession` (cost, kWh, location resolution); duplicate guard. |
| `ingest_location.py`           | Forward-geocodes an import's address → links/creates a named `Location`. |
| `cost.py`                      | Single source of truth for cost computation (precedence rule + edit-time re-rating). |
| `location_clustering.py` / `geocoding.py` | Clusters coordinates into per-user `Location` rows; forward/reverse geocoding providers. |
| `mileage_tracking.py`          | Annual mileage periods; current mileage derived from session odometers. |
| `dashboard_service.py` / `dashboard_trend.py` | Aggregation passes for the dashboard + daily spend chart.   |
| `insights_stats.py` / `usage_stats.py` | Numeric aggregators (car-filterable) behind the Insights page and the bot's grounded answers. |
| `ownership_trends.py`          | Read-time seasonal efficiency / derived range + indicative battery-capacity trend. |
| `car_lifetime.py`              | Per-car lifetime aggregation (ownership span, totals, efficiency, home/public) for the car-detail page. |
| `charge_planner.py`            | Multi-scenario charge planner: history-derived AC home power + a three-tier DC capability model. |
| `digest.py`                    | Weekly/monthly proactive-digest content builders (composed from the insights + mileage aggregators). |
| `backup.py`                    | VACUUM-INTO rotating SQLite snapshots with keep-last-N pruning.           |
| `mcp/` (`server.py`, `tools.py`) | FastMCP server + the user-scoped, two-phase propose/commit tool core (shared by the bot and external MCP clients). |

Routes are thin and live under `backend/plugtrack/api/routes/`. **Every query filters by `request.state.user_id`** — multi-user isolation is enforced at the query level, not by the database. Passwords are hashed with Argon2; mutating routes are CSRF-protected and login is rate-limited.

## Frontend

React 19 + Vite + Tailwind v4 + zustand. Zustand stores per domain (`auth`, `settings`); other domains are fetched through the typed API client on demand. Pages in `frontend/src/pages/`, shared primitives in `frontend/src/components/ui/`, the client in `frontend/src/api/client.ts`. Distance values flow through `formatDistance(km)` against the user's chosen unit; cost values through `formatCurrency(pence, currency)`.

Visual identity:

- "Electric" palette: green → cyan → blue gradient on charcoal-navy backgrounds.
- Inter typography (self-hosted, offline-capable) with tabular numerals.
- shadcn/ui primitives + Recharts for charts + Leaflet (OSM/CartoDB tiles) for the locations map.
- ⌘K command palette for navigation and theme toggle.

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
