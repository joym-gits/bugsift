# Start all bugsift services locally (without Docker)
# This script starts PostgreSQL, Redis, and then the backend

param(
    [switch]$SkipBackend = $false,
    [switch]$SkipFrontend = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  bugsift - Local Development Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running from correct directory
if (-not (Test-Path "..\backend\src\bugsift\main.py")) {
    Write-Host "✗ Error: Please run this script from the bugsift\scripts directory" -ForegroundColor Red
    exit 1
}

# Step 1: Start PostgreSQL
Write-Host "[1/4] Starting PostgreSQL..." -ForegroundColor Yellow
Set-Location $PSScriptRoot
& .\start-postgres.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to start PostgreSQL. Exiting." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Start Redis
Write-Host "[2/4] Starting Redis..." -ForegroundColor Yellow
& .\start-redis.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to start Redis. Exiting." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Run migrations
Write-Host "[3/4] Running database migrations..." -ForegroundColor Yellow
Set-Location ..\backend
.\venv\Scripts\activate
alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Migrations failed. Please check the error above." -ForegroundColor Red
    exit 1
}
Write-Host "✓ Migrations completed successfully" -ForegroundColor Green
Write-Host ""

# Step 4: Start backend
if (-not $SkipBackend) {
    Write-Host "[4/4] Starting backend server..." -ForegroundColor Yellow
    Write-Host "Backend will be available at: http://localhost:8000" -ForegroundColor Cyan
    Write-Host "API docs at: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop the backend" -ForegroundColor Yellow
    Write-Host ""
    
    uvicorn bugsift.api.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
} else {
    Write-Host "[4/4] Skipping backend (--SkipBackend flag set)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "To start backend manually:" -ForegroundColor Cyan
    Write-Host "  cd ..\backend" -ForegroundColor White
    Write-Host "  .\venv\Scripts\activate" -ForegroundColor White
    Write-Host "  uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src" -ForegroundColor White
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  bugsift is ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green