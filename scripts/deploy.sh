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

COMPOSE="docker compose -f compose-dev.yaml"

echo "==> ${COMPOSE} build"
${COMPOSE} build

echo "==> ${COMPOSE} up -d"
${COMPOSE} up -d

echo "==> ${COMPOSE} ps"
${COMPOSE} ps

cat <<EOF

Deploy submitted. Check container health with:
  ${COMPOSE} ps
  ${COMPOSE} logs -f plugtrack-api plugtrack-ui
EOF
