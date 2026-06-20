# PlugTrack

**PlugTrack is a self-hosted EV charging tracker you feed by screenshot.** You charge, screenshot the charging app — Tesla, Osprey, Electroverse, My Cupra, a home granny charger, anything — and send it to a **Telegram bot**. An AI vision model reads the energy, cost, location, state-of-charge and times off the image, merges multiple screenshots of the same charge into one record, and you confirm it with a single tap. Everything you charge ends up in one place: a clean web dashboard with spend, efficiency, mileage and per-car history.

> **No manufacturer API, no telematics.** PlugTrack reads the screenshots you already take, so it works with **any** charging network's app — not one car maker's data feed. (It began life pulling from the My Cupra cloud; when VW Group locked that third-party API down in 2026 the telematics path was removed entirely in v3.0. Screenshot ingestion is now the sole, OEM-agnostic input.)

## What it does

- **Captures charges effortlessly.** Snap the app, send to the bot, tap Save. The AI does the data entry; you just confirm.
- **Tells you what you spent and where.** Per-session cost, home-vs-public split, network breakdown, cost-per-mile, and a petrol-cost comparison — with your own tariffs and free-charging locations respected.
- **Tracks your driving.** Drop your odometer into a message and PlugTrack tracks mileage and tells you whether you're on pace for an annual or lease allowance.
- **Helps you decide.** A multi-scenario charge planner estimates how long a charge will take across home, AC and rapid-DC powers — using your own charging history — so you can plan an overnight top-up or judge whether a pricey rapid charger is worth it.
- **Remembers everything, per car.** Keep a lifetime history as you change vehicles, with long-term efficiency and an indicative battery-health trend.

## How you'd use it

You don't need to think about it day-to-day — it fits the habit you already have of glancing at the charging app when you unplug.

- **At a motorway rapid:** finish charging, screenshot the Tesla/Osprey/Electroverse app, send it to the bot, tap Save. Done — cost, kWh, location and the charge curve are captured.
- **At home overnight:** screenshot My Cupra (or just text the bot "home 9.3kwh 8h31m"); the granny-charger delivery is recorded at your home rate.
- **End of month:** open Insights to see exactly where the money went — home vs public, by network, by location — and whether your efficiency is drifting with the seasons.
- **Watching a lease allowance:** add your odometer occasionally; the dashboard shows whether you're tracking under or over your annual miles.
- **Before a trip:** open the Planner, pick a start/target SoC, and compare charge times at home vs a 50/150 kW rapid to plan your stops.
- **Quiet nudges:** opt in to a weekly or monthly Telegram digest so spend and mileage drift surface on their own — no need to go looking.

## Features

**Telegram ingestion (primary input)**

- Send one or more screenshots of a finished charge from any app; an OpenAI vision model extracts energy, cost, per-kWh, start/end times, SoC, location, network and the charge-power curve.
- Multiple screenshots of the same charge (e.g. the network app *and* My Cupra) auto-merge by overlapping time window into a single session — the model is **"Save = one charge"**.
- A photo **caption** ("home") or a **free-text note** (`home 9.3kwh 8h31m`) is parsed by the same model — no rigid syntax.
- **Per-charge car targeting** — with a single active car the charge is auto-assigned; with two or more, the bot replies with inline **tap-to-pick** buttons (or you can name the car in the caption). The choice sticks across screenshots merging into the same charge and resets on Save/Discard.
- **Home / granny-charger** charges: the metered *delivered* kWh is billed truth; SoC-banked energy and the AC→DC efficiency surface for free.
- An inline **confirm card** shows projected kWh + cost (including the home/location rate) and edits itself in place as more screenshots merge; one tap to Save or Discard. A duplicate-screenshot guard means re-sending a saved charge never double-counts.

**Conversational agent** — the bot is agentic. Beyond ingesting screenshots it can answer questions and make edits in plain language ("spend this month?", "how much on rapids?", "label that last charge as Home", "update session 42 from the next screenshot"). All actions go through a two-phase **propose → confirm → commit** flow, and every answer is grounded in a server-computed stats snapshot, so the model only restates real figures — it never invents numbers.

**Proactive summaries** — opt-in scheduled Telegram digests (weekly on Monday for the previous week; monthly on the 1st for the previous month, both off by default). Each digest is a quiet, glanceable recap — spend, energy, miles driven, and per-car mileage pace, each with a vs-previous-period delta; the monthly adds a home/public split.

**Multi-car** — run and retire several cars over their lifetime. Give cars **friendly names**; **archive** a replaced car (keeps all its history, drops off the dashboard) instead of deleting it; **reassign** any session to any car (active or archived); and **delete** is blocked once a car has charges (archive instead). Each car has a **detail / lifetime page** (ownership span + lifetime totals, efficiency, home/public split) and the whole Insights page can be **filtered to one car**.

**Mileage via text** — include an odometer in a message or caption (`home 12345mi 9.3kwh 8h31m`); it lands on the session and updates current mileage and annual mileage tracking (both derived from session odometers).

**Charging sessions** — full CRUD with a rich detail page built around the **charge-power curve** (AC and DC), plus duration, average/peak power, range added, cost-per-mile and a petrol-cost comparison. Reassign a session to another car, filter the list by car, and tag sources (`telegram`, `manual`, `import`).

**MyCupra CSV backfill** — a one-off importer (`python -m plugtrack.scripts.import_mycupra_csv`, dry-run by default, idempotent) seeds historical sessions from a My Cupra "charging statistics" export, including real energy-transfer time (`actual_charge_seconds`) distinct from the plug-in window.

**Insights** — analytics over your history, all filterable to a single car: spend/energy **over time**, **home vs public** split, **network** breakdown, **efficiency & cost-per-mile** trend, **seasonal efficiency & derived range** (monthly mi/kWh × battery, with a summer↔winter swing), an indicative **battery-health / capacity trend** (usable kWh over time, framed as a relative trend — not a certified SoH), and per-car **mileage-allowance pacing** (on track for your annual target). Plus a per-location breakdown with average p/kWh.

**Planner** — a multi-scenario, data-driven charge planner. Pick a car and a start/target SoC and see a table comparing your **home (actual)** power (derived from your real charge history), **7 kW / 11 kW** AC, **50 kW / 150 kW / car-max** DC, and a **custom kW** ("is this charger worth it at the stall?"). DC times use a three-tier model — your captured charge curves → SoC-aware averages of past rapids → a generic taper scaled to the car's ceiling — and every row carries a confidence tag (curve-derived · average-derived · modelled). Per-car **Max AC/DC kW** capability fields set the ceilings.

**Dashboard & analytics** — a per-car hero card showing last-known battery (after your most recent charge) and a summary of that charge, a 30-day spend chart, lifetime KPIs, recent sessions, and top locations. A locations map (OpenStreetMap) shows cost-banded markers.

**Admin** — one page for everything operational: integration setup (Telegram, OpenAI, geocoding), display/cost/charging preferences, locations & cars management (incl. archive/restore and capability fields), digest opt-in, scheduled **backups** + on-demand **CSV/JSON export**, and **MCP API tokens**.

**MCP server** — a FastMCP streamable-HTTP server at `/mcp/` exposes the same tool core (find/read charges, insights, and two-phase mutations) to any MCP client over bearer-token auth with read / readwrite scopes. Mint and revoke tokens from the Admin page.

**Bot health** — `/test` returns a health report (token + key validity, config completeness) straight to the chat.

## Screenshots

The dashboard answers "where's my battery and what did I last spend?" in one glance — a hero per-car card, a 30-day spend chart, lifetime KPIs, recent sessions, and top locations. Session detail is built around the charge-power curve. Locations is a real OpenStreetMap-tiled map with cost-banded markers (green = free, cyan = ~home rate, amber = expensive, red = very expensive).

## Documentation

- **[INSTALL.md](INSTALL.md)** — install & run (GHCR images, local dev, self-hosting from source) and configuration.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how it's built: services, backend/frontend, storage and project layout.
- **[RELEASING.md](RELEASING.md)** — container images, CI, and the automated release flow.
- **[CLAUDE.md](CLAUDE.md)** — conventions for working in this repo.
- **[backend/CONTRIBUTING.md](backend/CONTRIBUTING.md)** — backend contributor notes.

## Licence

See [`LICENSE`](LICENSE).
