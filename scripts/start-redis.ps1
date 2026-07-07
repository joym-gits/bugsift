# Start Redis on Windows
# Run this script to start Redis server

Write-Host "Starting Redis..." -ForegroundColor Cyan

# Check if Redis is installed
$redisPaths = @(
    "C:\Program Files\Redis\redis-server.exe",
    "C:\Redis\redis-server.exe",
    "C:\Program Files\Redis-x64-3.2.100\redis-server.exe"
)

$found = $false
foreach ($path in $redisPaths) {
    if (Test-Path $path) {
        $found = $true
        $redisDir = Split-Path $path
        
        Write-Host "Found Redis at: $redisDir" -ForegroundColor Green
        Write-Host "Starting Redis server..." -ForegroundColor Yellow
        
        # Start Redis in background
        Start-Process -FilePath $path -WorkingDirectory $redisDir -WindowStyle Hidden
        
        Start-Sleep -Seconds 1
        
        # Test connection
        try {
            $result = & redis-cli ping 2>&1
            if ($result -eq "PONG") {
                Write-Host "✓ Redis is running and accepting connections" -ForegroundColor Green
            } else {
                Write-Host "⚠ Redis started but ping failed" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "⚠ Could not test connection (redis-cli might not be in PATH)" -ForegroundColor Yellow
            Write-Host "  But Redis server should be running now" -ForegroundColor Yellow
        }
        break
    }
}

if (-not $found) {
    Write-Host "✗ Redis not found. Please install Redis first:" -ForegroundColor Red
    Write-Host "  Option 1 - Chocolatey: choco install redis" -ForegroundColor Cyan
    Write-Host "  Option 2 - Download: https://github.com/microsoftarchive/redis/releases" -ForegroundColor Cyan
    Write-Host "  Option 3 - WSL: sudo apt install redis-server" -ForegroundColor Cyan
    exit 1
}

Write-Host "`nRedis is now running on localhost:6379" -ForegroundColor Green