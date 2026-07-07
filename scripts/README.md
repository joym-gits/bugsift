# bugsift Scripts

Helper scripts for running bugsift locally without Docker.

## Quick Start

**Option 1: Run everything automatically (Recommended)**

```powershell
cd E:\Bug Sift\bugsift\scripts
.\start-all.ps1
```

This will:
1. Start PostgreSQL
2. Start Redis
3. Run database migrations
4. Start the backend server

**Option 2: Start services individually**

```powershell
# Terminal 1: Start PostgreSQL
cd E:\Bug Sift\bugsift\scripts
.\start-postgres.ps1

# Terminal 2: Start Redis
.\start-redis.ps1

# Terminal 3: Start backend
cd E:\Bug Sift\bugsift\backend
.\venv\Scripts\activate
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

## Prerequisites

Before running these scripts, make sure you have:

1. **PostgreSQL 15+** with pgvector extension installed
   - Download: https://www.postgresql.org/download/windows/
   - pgvector: https://github.com/pgvector/pgvector/releases

2. **Redis** installed
   - Chocolatey: `choco install redis`
   - Or download: https://github.com/microsoftarchive/redis/releases

3. **Python dependencies** installed
   ```powershell
   cd E:\Bug Sift\bugsift\backend
   .\venv\Scripts\activate
   pip install -e ".[dev]"
   ```

4. **Database created** and pgvector enabled
   ```powershell
   psql -U postgres -c "CREATE DATABASE bugsift;"
   psql -U postgres -d bugsift -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

## Scripts

### start-all.ps1
Master script that starts everything in order.

```powershell
# Start everything
.\start-all.ps1

# Skip backend (useful if you want to start it manually in debugger)
.\start-all.ps1 -SkipBackend
```

### start-postgres.ps1
Starts PostgreSQL service.

```powershell
.\start-postgres.ps1
```

### start-redis.ps1
Starts Redis server.

```powershell
.\start-redis.ps1
```

## Troubleshooting

### "PostgreSQL not found"
- Install PostgreSQL from https://www.postgresql.org/download/windows/
- Make sure to check "Add to PATH" during installation

### "Redis not found"
- Install Redis using Chocolatey: `choco install redis`
- Or download from https://github.com/microsoftarchive/redis/releases

### "Connection refused" error
- Make sure PostgreSQL service is running: `Get-Service *postgres*`
- Start it if needed: `net start postgresql-x64-15` (or your version)

### "pgvector extension missing"
```powershell
psql -U postgres -d bugsift -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### "Port 8000 already in use"
```powershell
# Find what's using the port
netstat -ano | findstr :8000

# Kill the process (replace PID with the number from above)
taskkill /PID <PID> /F

# Or use a different port
uvicorn bugsift.main:app --host 0.0.0.0 --port 8001 --reload --app-dir src
```

## VS Code Integration

You can also use VS Code tasks:

1. Open VS Code in `E:\Bug Sift\bugsift`
2. Press `Ctrl+Shift+B`
3. Select "Backend: Dev Server"

Or use the debugger:
1. Press `F5`
2. Select "FastAPI: Debug Backend"

## Access Points

Once running:
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/api/health
- Frontend (if running): http://localhost:3000

## Stopping Services

### Stop Backend
Press `Ctrl+C` in the backend terminal

### Stop Redis
```powershell
redis-cli shutdown
```

### Stop PostgreSQL
```powershell
# Find the service name
Get-Service *postgres*

# Stop it
net stop postgresql-x64-15  # Replace with your version
```

## Next Steps

After starting the backend:
1. Visit http://localhost:8000/docs to see the API
2. Follow the onboarding guide to set up GitHub App
3. Add your LLM API key in the dashboard
4. Install on a test repository

See also:
- `RUN_WITHOUT_DOCKER.md` - Complete guide for running without Docker
- `QUICK_START_LOCAL.md` - Quick start options including Docker