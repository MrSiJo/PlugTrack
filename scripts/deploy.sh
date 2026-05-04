#!/usr/bin/env bash
# Production deploy (bash).
#
# Refuses to run against the local Docker daemon — the active context
# must be a remote one. Runs `docker compose build` then
# `docker compose up -d` and reports container status.
#
# We don't curl the deployed health endpoint from this script: when
# deploying remotely the service may not be reachable from the
# developer machine. `docker compose ps` is the source of truth.

set -euo pipefail

context="$(docker context show)"
if [[ "${context}" == "default" ]]; then
    cat <<MSG >&2
Refusing to deploy against the 'default' Docker context.
Switch to a remote context first:
  docker context use <your-remote-context>
MSG
    exit 1
fi

echo "Deploying via context: ${context}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> docker compose build"
docker compose build

echo "==> docker compose up -d"
docker compose up -d

echo "==> docker compose ps"
docker compose ps

cat <<EOF

Deploy submitted. Check container health with:
  docker compose ps
  docker compose logs -f plugtrack-api plugtrack-ui
EOF
