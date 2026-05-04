# Local dev launcher (Windows / PowerShell).
#
# Validates that .env exists then prints the two commands you need to
# run in separate terminals. Doing the actual orchestration (Start-Job,
# split panes, etc.) varies enough between Windows Terminal / VS Code /
# tmux-on-WSL setups that we just print the canonical commands and let
# the human pick.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSCommandPath
$envPath = Join-Path $root '.env'

if (-not (Test-Path $envPath)) {
    Write-Host ".env not found at $envPath" -ForegroundColor Red
    Write-Host "  cp .env.example .env  (then edit APP_SECRET_KEY)" -ForegroundColor Yellow
    exit 1
}

Write-Host "PlugTrack dev — open two terminals and run:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Terminal 1 (backend):" -ForegroundColor Green
Write-Host "    cd backend"
Write-Host "    uvicorn plugtrack.main:create_app --factory --reload --port 9278"
Write-Host ""
Write-Host "  Terminal 2 (frontend):" -ForegroundColor Green
Write-Host "    cd frontend"
Write-Host "    npm run dev"
Write-Host ""
Write-Host "Then browse http://localhost:5173 (vite proxies /api/* to :9278)." -ForegroundColor Cyan
