<#
.SYNOPSIS
PDF2LaTeX — Development launcher (PowerShell)

.DESCRIPTION
Opens TWO separate terminal windows:
  1. Backend  — FastAPI + uvicorn on http://localhost:8000 (venv activated)
  2. Frontend — Vite dev server on http://localhost:5173 (bun)

Usage:  .\dev.ps1
Each window runs independently — close them when you're done.

.EXAMPLE
.\dev.ps1

.NOTES
If you see a "running scripts is disabled" error, run this once as admin:
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

$ErrorActionPreference = "Continue"
$ScriptDir = $PSScriptRoot

# ── Kill any leftover dev processes on the expected ports ──────────────
Write-Host "Cleaning up ports..." -ForegroundColor DarkGray
$ports = @(8000, 5173)
foreach ($port in $ports) {
    $ownerPids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
    $killed = 0
    foreach ($ownerPid in $ownerPids) {
        try {
            $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -match "^(python|uv|bun|node|vite)$") {
                Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
                $killed++
            }
        } catch { }
    }
    if ($killed -gt 0) {
        Write-Host "  Killed $killed process(es) on port $port" -ForegroundColor DarkGray
    }
}

# ── Open Backend terminal ──────────────────────────────────────────────
$backendCmd = "cd '$ScriptDir\backend'; Write-Host '===  Backend  ===' -ForegroundColor Blue; Write-Host '     http://localhost:8000' -ForegroundColor White; Write-Host '     http://localhost:8000/docs' -ForegroundColor DarkGray; if (Test-Path '.venv\Scripts\Activate.ps1') { . '.venv\Scripts\Activate.ps1'; Write-Host 'venv activated' -ForegroundColor DarkGray }; uv run python -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

# ── Open Frontend terminal ─────────────────────────────────────────────
$frontendCmd = @"
Write-Host "===  Frontend  ===" -ForegroundColor Green
Write-Host "     http://localhost:5173" -ForegroundColor White
Write-Host "Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

cd "$ScriptDir\frontend"
bun run dev
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

# ── Done ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Backend   → " -NoNewline
Write-Host "http://localhost:8000" -ForegroundColor Blue
Write-Host "  Frontend  → " -NoNewline
Write-Host "http://localhost:5173" -ForegroundColor Green
Write-Host "  API docs  → " -NoNewline
Write-Host "http://localhost:8000/docs" -ForegroundColor Blue
Write-Host ""
Write-Host "Press Ctrl+C in each window to stop, or close them." -ForegroundColor DarkGray
Write-Host ""
