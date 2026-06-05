#!/usr/bin/env pwsh
# Format and lint all code with Isort, Black and Ruff

Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Code Formatting & Linting" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check if environment exists and activate it
if (Test-Path -Path "./backend/.venv") {
    Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
    & ./backend/.venv/Scripts/Activate.ps1
} else {
    Write-Host "⚠️  Virtual environment not found" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Run Ruff formatter (import sorting + code formatting in one tool — no isort/black conflicts)
Write-Host "🎨 Running Ruff formatter..." -ForegroundColor Yellow
ruff format .
$formatExit = $LASTEXITCODE

if ($formatExit -eq 0) {
    Write-Host "✅ Ruff formatting completed successfully" -ForegroundColor Green
} else {
    Write-Host "❌ Ruff formatting failed with exit code $formatExit" -ForegroundColor Red
}

Write-Host ""

# Run Ruff linter (includes isort import sorting via the "I" rule)
Write-Host "🔍 Running Ruff linter with auto-fix..." -ForegroundColor Yellow
ruff check --fix .
$ruffExit = $LASTEXITCODE

if ($ruffExit -eq 0) {
    Write-Host "✅ Ruff linting completed successfully" -ForegroundColor Green
} else {
    Write-Host "⚠️  Ruff found issues (exit code $ruffExit)" -ForegroundColor Yellow
}

# bun linting
Write-Host "📦 Running bun linting in frontend/..." -ForegroundColor Yellow
Push-Location "frontend"
if (-not (Test-Path -Path "node_modules")) {
    Write-Host "📥 Installing frontend dependencies (bun install)..." -ForegroundColor Yellow
    bun install
}
bun run lint
$bunExit = $LASTEXITCODE
Pop-Location

if ($bunExit -eq 0) {
    Write-Host "✅ bun linting completed successfully" -ForegroundColor Green
} else {
    Write-Host "⚠️  bun linting found issues (exit code $bunExit)" -ForegroundColor Yellow
}

# bun tsc
Write-Host "📦 Running bun TypeScript compilation in frontend/..." -ForegroundColor Yellow
Push-Location "frontend"
bunx tsc --noEmit
$tscExit = $LASTEXITCODE
Pop-Location

if ($tscExit -eq 0) {
    Write-Host "✅ bun TypeScript compilation completed successfully" -ForegroundColor Green
} else {
    Write-Host "⚠️  bun TypeScript compilation found issues (exit code $tscExit)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Formatting Complete!" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan