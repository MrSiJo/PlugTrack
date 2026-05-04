# PlugTrack

PlugTrack v2 is a container-native EV charging tracker for Cupra Connect-equipped vehicles. A FastAPI backend pulls telematics from the official My Cupra cloud (via [pycupra](https://pypi.org/project/pycupra/)), synthesises charging sessions from the SoC stream, and serves them to a React 19 single-page app. There is no manual logging step — plug the car in, and a session appears once it finishes charging.

## What's new in v2

- **Container-first.** Two services (FastAPI API + nginx-served SPA) defined in `compose.yaml`. No Flask, no Jinja templates, no jQuery.
- **FastAPI + React 19 rewrite.** Async SQLAlchemy 2.x on the backend; Vite + Tailwind 4 + zustand on the frontend.
- **Live SSE sync streaming.** `POST /api/sync/{car_id}` returns a `stream_url` the browser subscribes to over Server-Sent Events for play-by-play sync events.
- **Telematics-first session synthesis.** A state machine consumes the polled SoC + charging-status stream and emits one `ChargingSession` per plug-in cycle, with cost computed against the location overlay (free / per-kWh / home rate / overrides).
- **Location auto-clustering.** Plug-in coordinates are clustered into per-user locations with reverse-geocoded addresses; labelling a location retro-recomputes past sessions' costs.
- **Plugin contract for future history providers.** `ChargingHistoryProvider` exists in `backend/plugtrack/plugins/` so a future personal plugin can backfill from a richer source without re-architecting.

## Quickstart

### 1. Clone & configure

```bash
git clone <your-fork-or-this-repo>
cd PlugTrack
cp .env.example .env
```

Generate a real `APP_SECRET_KEY` (the loader rejects placeholders and anything shorter than 32 chars) and paste it into `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. Local dev

In one terminal — backend (factory mode is required so the lifespan handler runs):

```bash
cd backend
pip install -r requirements.txt
uvicorn plugtrack.main:create_app --factory --port 9278
```

In another — frontend (Vite dev server proxies `/api` to `localhost:9278`):

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints, complete first-run setup, then add your Cupra Connect credentials in **Settings → Cupra Connect** to start syncing. (No credentials needed to explore the UI; the sync orchestrator is happy to sit idle.)

### 3. Deploy

```bash
docker context use <your-remote-context>   # never deploy against `default`
scripts/deploy.ps1                          # PowerShell
# or
scripts/deploy.sh                           # bash
```

The deploy scripts refuse to run if the active Docker context is `default` — guarding against accidentally deploying to the developer machine.

## Architecture overview

The backend is a single-worker FastAPI app. A lifespan handler asserts `WEB_CONCURRENCY=1` (plus a filesystem lock) so SQLite + the in-process APScheduler stay correct, then wires three long-lived services into `app.state`: an event bus (for SSE fan-out), a per-car sync orchestrator (serialises syncs per vehicle), and an adaptive scheduler (varies poll cadence with charging state). Routes are thin wrappers over services in `backend/plugtrack/services/`; every query filters by `user_id` for multi-user isolation. Cost computation has a strict precedence rule (`override_total` > `override_per_kwh` > `location_free` > `location_rate` > `home_rate` > `unknown`) implemented once in `services/cost.py`.

The frontend is a Vite-built React SPA served by nginx in production. It owns no charging logic — it reads the same JSON the API exposes, and the dashboard, sessions list, session detail, settings, and locations admin pages are pure render-from-state. The full design is documented in [`docs/superpowers/specs/2026-05-04-plugtrack-rebuild-design.md`](docs/superpowers/specs/2026-05-04-plugtrack-rebuild-design.md).

## Out of scope (for now)

The undocumented Cariad `multicharge` BFF used by the **My Cupra** mobile app for full charging history is **not** shipped here. That endpoint is officially internal, would tie us to a single OEM tenancy, and pycupra does not cover it. The plugin contract `ChargingHistoryProvider` exists in `backend/plugtrack/plugins/` for any future personal-plugin implementation; nothing in mainline depends on it being installed.

Phase 0 reverse-engineering notes for that BFF — including request shapes captured during a probe — live in `docs/pycupra-findings.md`. **That file is gitignored and only exists locally**; it is not shipped with the repo and contains personal account material.

## Reference

- Spec: [`docs/superpowers/specs/2026-05-04-plugtrack-rebuild-design.md`](docs/superpowers/specs/2026-05-04-plugtrack-rebuild-design.md)
- Plan: [`docs/superpowers/plans/2026-05-04-plugtrack-rebuild.md`](docs/superpowers/plans/2026-05-04-plugtrack-rebuild.md)
- Project conventions for Claude Code: [`CLAUDE.md`](CLAUDE.md)
- Legacy v1 Flask code is preserved on disk under `legacy/` for reference but is gitignored and untracked from origin.

## Licence

See [`LICENSE`](LICENSE).
