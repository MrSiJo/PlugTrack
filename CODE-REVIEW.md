# PlugTrack — Code Quality Review

**Date:** 2026-07-08 · Part of a review of all `*Track` apps; cross-app index at `C:\code\TRACK-APPS-CODE-REVIEW.md`.

## How to use this document (instructions for a Claude session)

This is a code-quality review of PlugTrack, one of Simon's personal projects. If you've been given finding IDs (e.g. "implement PLUG-H1 and PLUG-M4"):

1. **IDs** are `PLUG-<PRIORITY><n>` — `H` high, `M` medium, `L` low/polish.
2. **Scope discipline:** findings are about code quality, correctness, optimisation, and consistency — do NOT add features, change end-user functionality, or redesign UI. Keep each fix minimal and targeted.
3. **This is a personal project** — don't add enterprise ceremony unless a finding explicitly calls for it.
4. **Verify line numbers before editing** — this is a snapshot from 2026-07-08; re-locate code by the symbols/strings named in the finding.
5. Run the test suites (pytest — ~1,004 backend tests; vitest frontend) before and after changes; each finding's `Verify:` note gives a functional check.
6. **Secrets:** untracked local `.env` files are known and fine — do not "fix" them.
7. **Commits:** one per finding (or tightly-related group), message referencing the ID, e.g. `fix: reply to user when screenshot extraction fails (PLUG-H1)`.

**Effort key:** `quick` = minutes, single-file · `small` = under an hour · `involved` = multi-file / needs care and testing.

---

**Stack:** Python 3.12 / FastAPI + async SQLAlchemy 2 + SQLite (aiosqlite) + APScheduler backend; React 19 + TypeScript + Vite + Tailwind 4 + zustand frontend; two-container Docker (nginx SPA proxy + API) with multi-arch GHCR images built by GitHub Actions and release-please.

**Overall assessment:** An unusually healthy hobby codebase — ~1,000 passing backend tests, a pinned security-invariants test for auth/CSRF exempt paths, pre-commit gitleaks/bandit/ruff, non-root containers with healthchecks and restart policies, and consistently excellent docstrings that document trade-offs. No secrets are tracked in git (`.env`, `pycupra_data/`, `snapshots/`, `www/`, `docs/`, `legacy/` are all correctly ignored and untracked). The main accumulated debt is the half-finished amputation of the pycupra/live-sync subsystem (removed in v3.0) whose remnants still thread through config, models, API surface, nginx, and tracked scripts, plus a few failure-path and resource-lifecycle gaps in the background jobs.

## High priority

### PLUG-H1 — Screenshot ingestion fails silently to the user when OpenAI (or Telegram file download) errors
*(effort: small)*
`backend/plugtrack/services/telegram_ingest.py:800` (`result = await ctx.extractor(image)`) and the `get_file_path`/`download_file` calls at `telegram_ingest.py:761-762` are unguarded; the only catch is `run_bot`'s blanket `logger.exception("telegram update handling failed")` at `telegram_ingest.py:1339-1342`. There is also no retry/backoff for 429/5xx in `screenshot_extraction.py:call_openai` (only a one-shot retry for the `reasoning.effort` 400). Since this is the app's primary input flow, an OpenAI outage means the user sends a screenshot and gets *nothing back* — the photo is simply lost.
**Fix:** wrap the extraction path in `handle_photo` with a try/except that replies "couldn't read that screenshot — please resend", and optionally add one retry with short backoff on 429/5xx.
**Verify:** force an OpenAI error (bad key), send a screenshot — Telegram must reply with a failure message.

### PLUG-H2 — Test suite is environment-dependent: fails on any checkout with a root `.env`
*(effort: quick)*
`backend/tests/test_bootstrap.py:7` (`test_settings_requires_app_secret_key`) deletes the env var but `bootstrap.py:33` sets `env_file=".env"`, so pydantic-settings loads the repo-root `.env` and `Settings()` happily instantiates. Verified: 1 failed / 1,003 passed on this machine.
**Fix:** instantiate `Settings(_env_file=None)` in the test (or `monkeypatch.chdir(tmp_path)`).
**Verify:** full suite passes with a populated root `.env` present.

### PLUG-H3 — Nominatim rate limit is per-instance, not global
*(effort: quick)*
`geocoding.py:424` `get_provider()` constructs a fresh `NominatimProvider()` (each with its own `_RateLimiter`) at five call sites (`telegram_ingest.py:1013`, `mcp/tools.py:390` and `:511`, `ingest_location.py:184`, `api/routes/geocode.py:50`). The module docstring says "we serialise + sleep via an asyncio.Lock", but concurrent geocodes from different call sites can exceed Nominatim's 1 req/s ToS.
**Fix:** a module-level shared `_RateLimiter` (or `functools.lru_cache` the provider instance).

## Medium priority

### PLUG-M1 — Dead pycupra/live-sync surface still threaded through the app
*(effort: involved)*
`dashboard_service.py:140-212` sets 11 `CarPanel` fields (`last_state`, `next_poll_at`, `active_job_id`, `charging_power_kw`, `target_soc`, `battery_care`, `charging_cable_connected`, `charging_estimated_end_at`, …) unconditionally to `None`/`False` with comments admitting the subsystem is gone; they're typed in `frontend/src/api/client.ts:962-975` but consumed by no page. `models/plug_in_record.py` has no production writer (only test fixtures create rows; `routes/locations.py:485,559` still merge them), and `Location.visit_count` is only ever 0 for new data. The `/api/cars/:id/image` route (`routes/cars.py:225`), `PYCUPRA_IMAGE_DIR` env in both compose files, the `plugtrack-www` volume, and the Dockerfile's `mkdir /app/data/pycupra` all serve files nothing writes any more.
**Fix:** one deliberate cleanup pass: drop the always-None fields end-to-end, delete `PlugInRecord` + its merge logic, and decide whether cached car images are worth keeping the route/volume for.
**Verify:** tests pass; dashboard renders identically; grep for the removed field names returns nothing.

### PLUG-M2 — Dead SSE plumbing: nginx proxies to a route that doesn't exist; `sse-starlette` unused
*(effort: quick)*
`frontend/nginx.conf` has a dedicated `/api/sync/stream` location (buffering off, 86400s read timeout) for a `routes/sync.py` that was removed in the pivot; `sse-starlette==2.1.3` in `backend/requirements.txt` has zero imports. Remove both.

### PLUG-M3 — ~1,500 lines of dead Cupra probe scripts still tracked
*(effort: quick)*
`scripts/pycupra_probe.py` (1,185 lines), `scripts/extract_cupra_endpoints.py`, `scripts/list_cupra_vins.py` all depend on the removed pycupra stack and `.env.probe`; `scripts/backfill_session.py`'s docstring describes the removed sync/phantom-detector subsystem.
**Fix:** delete the three probe scripts (git history keeps them) and refresh the backfill docstring — it's the only one still genuinely useful.

### PLUG-M4 — Hourly digest tick leaks an httpx client
*(effort: quick)*
`main.py:193` creates `client = client_factory(token)` (a `TelegramClient` owning an `httpx.AsyncClient`) on every tick that passes the enable/token/allowlist gates, and never calls `aclose()`. That's a leaked connection pool per hour of uptime.
**Fix:** construct it lazily only when a digest is actually due, and close it in a `finally`.

### PLUG-M5 — Hardcoded seeded MQTT password `"oil"`
*(effort: quick)*
`main.py:413` (`seed_mqtt_password`) writes `encrypt_secret("oil", …)` as every fresh install's MQTT password. It looks like a personal broker password baked into a public repo, and it silently pre-fills a wrong credential for everyone else.
**Fix:** leave the row unset and let the Admin page require entry.

### PLUG-M6 — Copy-paste duplication in the two OpenAI call paths and six geocoding request bodies
*(effort: small)*
`screenshot_extraction.py:224-252` (`call_openai`) and `:272-296` (`extract_from_text`) are ~90% identical (effort-400 retry, incomplete check, parse); the three geocoding providers repeat the borrow-or-own-client/try/finally/aclose boilerplate six times (`geocoding.py:146-410`).
**Fix:** extract a single `_post_responses(payload, …)` helper and a shared `_get_json(url, params)` helper respectively.
**Verify:** tests pass; both extraction paths and all three geocoders behave identically.

## Low priority / polish

### PLUG-L1 — SQLite engine has no PRAGMA setup
*(effort: quick)* — `db.py:20`: `foreign_keys` is OFF (FK constraints silently unenforced — app-level checks compensate), no `busy_timeout`. A connect-event listener issuing `PRAGMA foreign_keys=ON` is cheap insurance.

### PLUG-L2 — Session cookie never expires server-side
*(effort: quick)* — `auth_middleware.py` uses `URLSafeSerializer` (no timestamp); `session_max_age_seconds` only sets the browser-side cookie max-age, so a captured cookie is valid until the secret rotates. Swap to `URLSafeTimedSerializer` + `max_age=` in `loads`.

### PLUG-L3 — Private cross-module imports
*(effort: quick)* — `ha_publisher.py:80` calls `insights_stats._miles_driven_km`; `telegram_ingest.py:22-24` imports `_max_odo_at_or_before` and `_distance_unit`. Rename to public or add public wrappers.

### PLUG-L4 — km↔mi constant defined four times
*(effort: quick)* — `mileage_tracking.KM_PER_MILE`, `session_metrics.py:41 _KM_PER_MILE`, `mcp/tools.py:57 _KM_PER_MI`, plus `formatting.km_to_mi`. Centralise in `services/formatting.py`.

### PLUG-L5 — Backend image installs `git` it never uses
*(effort: quick)* — `backend/Dockerfile` apt-installs `git` but `requirements.txt` has no VCS deps. Drop it.

### PLUG-L6 — Eight unused `@radix-ui/react-*` dependencies
*(effort: quick)* — `frontend/package.json` lists individual scoped packages, but all UI primitives import from the `radix-ui` umbrella package only. Remove the scoped ones.

### PLUG-L7 — `bootstrap.py:60` error message references nonexistent `scripts/bootstrap.{sh,ps1}`
*(effort: quick)* — the actual guidance lives in `compose.yaml`'s header (`python -c "import secrets; …"`). Point the message there.

### PLUG-L8 — `legacy/` carries a full committed-to-disk virtualenv
*(effort: quick)* — correctly gitignored and untracked, so no repo action needed; but `legacy/plugtrack/venv/` (with site-packages) and its own `.pytest_cache` sit on disk. Safe to delete the venv and keep just the Flask source for reference.

## Patterns snapshot

- **Config:** env vars via pydantic-settings (`.env`, `APP_SECRET_KEY` validated at startup) for infra; runtime app config in a DB `setting` catalogue with Fernet-encrypted secret rows; `.env.example` tracked
- **Logging:** stdlib `logging`, module-level loggers, `logger.exception` in swallow-and-continue background jobs; no structured logging
- **DB access:** async SQLAlchemy 2.0 + aiosqlite, session-per-operation via `async_sessionmaker`; no Alembic — idempotent additive `ALTER TABLE` migrations hand-maintained in `main.py`
- **Frontend:** React 19 + TypeScript + Vite + Tailwind 4 + zustand (2 stores) + shadcn/radix + Recharts + Leaflet; typed hand-rolled fetch client with CSRF double-submit
- **Tests:** pytest + pytest-asyncio, ~1,004 backend tests (fresh tmp SQLite per test); vitest + Testing Library with substantial page-level coverage; a Playwright screenshots script (not e2e tests)
- **Docker:** two containers (nginx SPA reverse-proxying → API), healthchecks on both, non-root API user + tini, `restart: unless-stopped`, API bound to loopback; separate GHCR-pull and source-build compose files
- **Lint/format:** ruff (+ format) + bandit + gitleaks + custom RFC-1918-IP blocker via pre-commit; eslint + `tsc -b` on the frontend; release-please + multi-arch image CI
- **Scripts:** both PowerShell and bash provided in pairs (`dev.ps1`/`dev.sh`, `deploy.ps1`/`deploy.sh`); Python for operational one-offs
