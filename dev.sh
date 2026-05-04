#!/usr/bin/env bash
# Local dev launcher (Linux / macOS / WSL).
#
# Validates that .env exists then prints the two commands to run in
# separate terminals. We don't background processes from a single
# script because juggling stdout/stderr across two reload-heavy
# servers in one pane is more confusing than helpful.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${ROOT}/.env"

if [[ ! -f "${ENV_PATH}" ]]; then
    echo ".env not found at ${ENV_PATH}" >&2
    echo "  cp .env.example .env   # then edit APP_SECRET_KEY" >&2
    exit 1
fi

cat <<EOF
PlugTrack dev — open two terminals and run:

  Terminal 1 (backend):
    cd backend
    uvicorn plugtrack.main:create_app --factory --reload --port 9278

  Terminal 2 (frontend):
    cd frontend
    npm run dev

Then browse http://localhost:5173 (vite proxies /api/* to :9278).
EOF
