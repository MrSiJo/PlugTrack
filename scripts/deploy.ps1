# Production deploy (PowerShell).
#
# Refuses to run against the local Docker daemon — the active context
# must be a remote one. Runs `docker compose build` then
# `docker compose up -d` and reports container status.
#
# We deliberately don't curl the deployed health endpoint from this
# script: when deploying remotely the service URL/port may not be
# reachable from the developer machine (e.g. firewalled to the LAN).
# `docker compose ps` is the source of truth — health is reflected
# there once the container's HEALTHCHECK passes.

$ErrorActionPreference = 'Stop'

$context = (docker context show).Trim()
if ($context -eq 'default') {
    Write-Host "Refusing to deploy against the 'default' Docker context." -ForegroundColor Red
    Write-Host "  Switch to a remote context first:" -ForegroundColor Yellow
    Write-Host "    docker context use <your-remote-context>"
    exit 1
}

Write-Host "Deploying via context: $context" -ForegroundColor Cyan

$root = Split-Path -Parent $PSScriptRoot

$compose = @('compose', '-f', 'compose-dev.yaml')

Push-Location $root
try {
    Write-Host "==> docker compose -f compose-dev.yaml build" -ForegroundColor Green
    docker @compose build
    if ($LASTEXITCODE -ne 0) { throw "build failed" }

    Write-Host "==> docker compose -f compose-dev.yaml up -d" -ForegroundColor Green
    docker @compose up -d
    if ($LASTEXITCODE -ne 0) { throw "up failed" }

    Write-Host "==> docker compose -f compose-dev.yaml ps" -ForegroundColor Green
    docker @compose ps
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Deploy submitted. Check container health with:" -ForegroundColor Cyan
Write-Host "  docker compose -f compose-dev.yaml ps"
Write-Host "  docker compose -f compose-dev.yaml logs -f plugtrack-api plugtrack-ui"
