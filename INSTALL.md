# Installing & running PlugTrack

PlugTrack ships as two containers (`plugtrack-api` + `plugtrack-ui`). Pick one of the paths below. For how it's built, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for how releases are cut, see [`RELEASING.md`](RELEASING.md).

## Quickstart — pull images from GHCR

The easiest path. You need `docker` (with `compose`) and a way to generate a random secret. No source code, no build toolchain, no Python.

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

- Add a car in **Admin → Cars** (make, model, battery size, efficiency; optionally a friendly name and Max AC/DC kW for the planner).
- In **Admin → Integrations**, paste your Telegram bot token and OpenAI API key (both encrypted at rest), set your allowed Telegram user id(s), and enable the bot and AI. (No "default car" needed — the bot resolves the target car per charge.)
- Message your bot a charge screenshot, confirm the card, and the session appears on the dashboard.

### Pinning a specific image tag

`compose.yaml` defaults to `:latest`. To pin a release:

```bash
echo "PLUGTRACK_TAG=3.4.2" >> .env
docker compose pull && docker compose up -d
```

Available tags live on the GHCR package pages:

- https://github.com/MrSiJo/PlugTrack/pkgs/container/plugtrack-api
- https://github.com/MrSiJo/PlugTrack/pkgs/container/plugtrack-ui

Or check https://github.com/MrSiJo/PlugTrack/releases for the matching changelog. Both images are multi-arch (`linux/amd64` + `linux/arm64`).

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

## Setting up the Telegram bot & OpenAI

The bot and the AI vision extraction are the heart of PlugTrack. Both are configured in **Admin → Integrations** after first-run setup; nothing here touches the `.env` file. Secrets are encrypted at rest with your `APP_SECRET_KEY`.

### 1. Create your Telegram bot

PlugTrack talks to Telegram through a bot you own.

1. In Telegram, open a chat with **[@BotFather](https://t.me/BotFather)** (the official bot factory) and send `/newbot`.
2. Follow the prompts: give it a **display name** (anything, e.g. "My PlugTrack") and a **username** that must end in `bot` (e.g. `my_plugtrack_bot`).
3. BotFather replies with an **HTTP API token** that looks like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. Copy it — this is your **bot token**.

### 2. Find your Telegram user ID

PlugTrack only accepts messages from user IDs you allow-list (so a stranger who finds your bot can't feed it data).

1. In Telegram, open **[@userinfobot](https://t.me/userinfobot)** (or `@RawDataBot`) and send it any message.
2. It replies with your numeric **Id** (e.g. `123456789`). Copy it.

### 3. Get an OpenAI API key

The vision model that reads your screenshots runs on the OpenAI API.

1. Sign in at **[platform.openai.com](https://platform.openai.com)** (this is the developer platform — a paid, pay-as-you-go API, **separate from a ChatGPT Plus subscription**).
2. Add a payment method / credits under **Settings → Billing** (the API won't work without billing set up).
3. Under **API keys**, create a new secret key — it starts with `sk-…`. Copy it now; you can't view it again later.

> **Cost:** extraction is cheap — a screenshot is a few hundred tokens, so reading a charge costs a fraction of a penny. You can cap spend with a monthly usage limit in the OpenAI dashboard.

### 4. Enter everything in PlugTrack Admin → Integrations

| Card | Field (Admin label) | Value |
| --- | --- | --- |
| **Telegram** | Telegram bot token | the BotFather token from step 1 |
| **Telegram** | Allowed Telegram user IDs | your numeric ID from step 2 (comma-separate multiple) |
| **Telegram** | Telegram bot enabled | **on** |
| **AI** | OpenAI API key | the `sk-…` key from step 3 |
| **AI** | OpenAI vision model | leave the default (`gpt-5.5`) unless you want another vision-capable model |
| **AI** | AI features enabled | **on** (master switch for extraction + the conversational bot) |

Optional:

- **AI → OpenAI input/output price (pence / 1k tokens):** fill these to see a £ cost per extraction; leave blank to show token counts only.
- **Display → Public base URL:** your externally reachable UI URL (e.g. `http://your-host:9279`) so the bot's confirm cards can deep-link back to the saved session. Leave blank to omit the link.

The bot reconciles **live** when you save these — no redeploy needed. It runs as an always-on long-poll task gated by `telegram_bot_enabled` / `ai_enabled`.

### 5. Start the bot and verify

1. In Telegram, open a chat with **your** bot (search its `@username`) and send it any message — Telegram requires you to message a bot first before it can reply to you.
2. Send **`/test`**: the bot replies with a health report (token + key validity, config completeness). A green report means you're ready.
3. Send a charge screenshot. The bot extracts it, shows a confirm card with the projected kWh and cost, and one tap saves it to your dashboard.

If `/test` reports a problem, re-check the token (no stray spaces), that your user ID is in the allow-list, that both **Telegram bot enabled** and **AI features enabled** are on, and that your OpenAI key has billing/credit.

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
- **Integrations — Telegram & AI:** Telegram bot token, allowed Telegram user id(s), OpenAI API key + model, optional input/output token prices (for cost accounting), and opt-in **weekly / monthly digest** toggles + send hour. The bot runs as a lifespan background task, gated by `telegram_bot_enabled` / `ai_enabled`, and reconciles live when you change its settings — no redeploy. (The bot resolves the target car per charge; there is no "default car" setting.)
- **Integrations — Geocoding:** provider (`nominatim` default — free and keyless), optional API key for Mapbox / OpenCage, cluster radius.
- **Charging defaults:** default home rate (p/kWh), home-charge window, fallback power (kW), charging loss factor, petrol price (p/L), petrol MPG (used for the petrol comparison).
- **Backup:** enable scheduled snapshots, interval, retention count.

Secrets (Telegram token, OpenAI key) are encrypted at rest with `APP_SECRET_KEY` — rotating that secret renders them unreadable, so plan accordingly.

## Storage layout

Run with the default `compose.yaml` (named volumes, managed by Docker):

| Volume               | Mounted at  | Contents                                                       |
| -------------------- | ----------- | -------------------------------------------------------------- |
| `plugtrack-data`     | `/app/data` | SQLite DB + rotating backup snapshots (`/app/data/backups`).   |
| `plugtrack-logs`     | `/app/logs` | App logs.                                                      |
| `plugtrack-www`      | `/app/www`  | Cached per-VIN car images served by `/api/cars/:id/image` (no longer auto-refreshed since telematics was removed; any previously cached image still displays). |

Run with `compose-dev.yaml` and the same paths bind to `/dockerdata/plugtrack/{data,logs,www}` on the host instead — easier to inspect, less portable.
