# Start PostgreSQL on Windows
# Run this script to start your PostgreSQL service

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan

# Try to find and start PostgreSQL service
$services = Get-Service | Where-Object {$_.Name -like "*postgres*" -or $_.DisplayName -like "*postgres*"}

if ($services) {
    Write-Host "Found PostgreSQL services:" -ForegroundColor Green
    $services | Format-Table Name, DisplayName, Status -AutoSize
    
    foreach ($service in $services) {
        if ($service.Status -ne 'Running') {
            Write-Host "Starting $($service.Name)..." -ForegroundColor Yellow
            Start-Service $service.Name
            Write-Host "✓ Started $($service.Name)" -ForegroundColor Green
        } else {
            Write-Host "✓ $($service.Name) is already running" -ForegroundColor Green
        }
    }
} else {
    Write-Host "No PostgreSQL service found. Trying to start manually..." -ForegroundColor Yellow
    
    # Try common PostgreSQL installation paths
    $paths = @(
        "C:\Program Files\PostgreSQL\15\bin\pg_ctl.exe",
        "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe",
        "C:\Program Files\PostgreSQL\14\bin\pg_ctl.exe"
    )
    
    $found = $false
    foreach ($path in $paths) {
        if (Test-Path $path) {
            $found = $true
            $pgBin = Split-Path $path
            $pgData = $pgBin -replace '\\bin$', '\data'
            
            Write-Host "Found PostgreSQL at: $pgBin" -ForegroundColor Green
            Write-Host "Starting PostgreSQL with data directory: $pgData" -ForegroundColor Yellow
            
            & $path -D $pgData start
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✓ PostgreSQL started successfully" -ForegroundColor Green
            } else {
                Write-Host "✗ Failed to start PostgreSQL" -ForegroundColor Red
            }
            break
        }
    }
    
    if (-not $found) {
        Write-Host "✗ PostgreSQL not found. Please install PostgreSQL first:" -ForegroundColor Red
        Write-Host "  https://www.postgresql.org/download/windows/" -ForegroundColor Cyan
        exit 1
    }
}

# Wait a moment for PostgreSQL to fully start
Write-Host "`nWaiting for PostgreSQL to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

# Test connection
Write-Host "`nTesting connection..." -ForegroundColor Cyan
try {
    $env:PGPASSWORD = "sumanth123"
    $result = & psql -U postgres -h localhost -p 5432 -c "SELECT 1;" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ PostgreSQL is running and accepting connections" -ForegroundColor Green
        Write-Host "`nYou can now run: alembic upgrade head" -ForegroundColor Cyan
    } else {
        Write-Host "⚠ PostgreSQL started but connection test failed" -ForegroundColor Yellow
        Write-Host "  This might be normal if the database 'bugsift' doesn't exist yet" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠ Could not test connection (psql might not be in PATH)" -ForegroundColor Yellow
    Write-Host "  But PostgreSQL service should be running now" -ForegroundColor Yellow
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "1. Create database: psql -U postgres -c `"CREATE DATABASE bugsift;`"" -ForegroundColor White
Write-Host "2. Enable pgvector: psql -U postgres -d bugsift -c `"CREATE EXTENSION IF NOT EXISTS vector;`"" -ForegroundColor White
Write-Host "3. Run migrations: alembic upgrade head" -ForegroundColor White
Write-Host "4. Start backend: uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src" -ForegroundColor White