# Running bugsift WITHOUT Docker - Step by Step

This guide shows how to run each component separately on Windows without Docker.

## Architecture Overview

You'll run these services separately:
1. **PostgreSQL** (with pgvector) - Database
2. **Redis** - Queue/cache
3. **Backend** (FastAPI) - API server
4. **Frontend** (Next.js) - Dashboard (optional)

---

## Step 1: Install PostgreSQL with pgvector

### Option A: Using Installer (Easiest)

1. **Download PostgreSQL:**
   - Visit https://www.postgresql.org/download/windows/
   - Download PostgreSQL 15 or 16 for Windows
   - Run the installer
   - **Remember the password you set for `postgres` user**

2. **Download pgvector:**
   - Visit https://github.com/pgvector/pgvector/releases
   - Download `pgvector-0.5.1-windows-x64.exe` (or latest version)
   - Run the installer
   - It will automatically detect your PostgreSQL installation

3. **Verify pgvector installation:**
   ```powershell
   # Open PowerShell as Administrator
   # Navigate to PostgreSQL bin directory (adjust path if needed)
   cd "C:\Program Files\PostgreSQL\15\bin"
   
   # Connect to PostgreSQL
   .\psql -U postgres
   
   # Enter your password, then run:
   CREATE EXTENSION IF NOT EXISTS vector;
   \q
   ```

### Option B: Using Chocolatey

```powershell
# Install PostgreSQL
choco install postgresql15 --params "/Password:YourPassword"

# Install pgvector
choco install pgvector

# Verify
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Step 2: Install Redis for Windows

### Option A: Using Chocolatey (Easiest)

```powershell
choco install redis
```

### Option B: Using Windows Subsystem for Linux (WSL)

```powershell
# In WSL terminal
sudo apt update
sudo apt install redis-server
redis-server --daemonize yes
```

### Option C: Download Pre-built Binary

1. Visit https://github.com/microsoftarchive/redis/releases
2. Download `Redis-x64-3.2.100.msi` (or latest)
3. Install and run as a service

### Verify Redis is Running

```powershell
redis-cli ping
# Should return: PONG
```

---

## Step 3: Create Database

```powershell
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE bugsift;

# Verify
\l

# Exit
\q
```

---

## Step 4: Update .env File for Local Services

Your current `.env` has Docker service names. Update it for local services:

```powershell
cd E:\Bug Sift\bugsift
notepad .env
```

**Change these lines:**

```env
# OLD (Docker):
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://postgres:sumanth123@postgres:5432/bugsift
REDIS_HOST=redis
REDIS_URL=redis://redis:6379/0

# NEW (Local):
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://postgres:sumanth123@localhost:5432/bugsift
REDIS_HOST=localhost
REDIS_URL=redis://localhost:6379/0
```

**Save and close the file.**

---

## Step 5: Install Python Dependencies

You already did this, but verify:

```powershell
cd E:\Bug Sift\bugsift\backend

# Activate venv (already done)
.\venv\Scripts\activate

# Install dependencies (already done)
pip install -e ".[dev]"
```

---

## Step 6: Run Database Migrations

```powershell
cd E:\Bug Sift\bugsift\backend

# Make sure venv is activated
.\venv\Scripts\activate

# Run migrations
alembic upgrade head

# Should see:
# INFO  [alembic.runtime.migration] Running upgrade  -> 0000_baseline, initial baseline
# INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
# INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

---

## Step 7: Start the Backend

```powershell
cd E:\Bug Sift\bugsift\backend

# Make sure venv is activated
.\venv\Scripts\activate

# Start backend
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

**You should see:**
```
INFO:     Started server process [xxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Keep this terminal open!** The backend is now running.

---

## Step 8: Test the Backend

Open a new PowerShell window:

```powershell
# Test health endpoint
curl http://localhost:8000/api/health

# Should return:
# {"status":"ok","version":"0.x.x"}

# Or open in browser:
start http://localhost:8000/api/health
start http://localhost:8000/docs  # API documentation
```

---

## Step 9: Start the Frontend (Optional)

If you want the dashboard too:

```powershell
# Open a new PowerShell window
cd E:\Bug Sift\bugsift\frontend

# Install dependencies (first time only)
npm install

# Start frontend
npm run dev
```

**Access:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

---

## Complete Workflow (Every Time You Start)

### Terminal 1: Start PostgreSQL
```powershell
# Usually runs as a service automatically
# If not, start it:
net start postgresql-x64-15
```

### Terminal 2: Start Redis
```powershell
# If installed as service, it runs automatically
# Otherwise:
redis-server
```

### Terminal 3: Start Backend
```powershell
cd E:\Bug Sift\bugsift\backend
.\venv\Scripts\activate
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

### Terminal 4: Start Frontend (Optional)
```powershell
cd E:\Bug Sift\bugsift\frontend
npm run dev
```

---

## Using VS Code

### Method 1: Using Tasks

1. Open VS Code in `E:\Bug Sift\bugsift`
2. Press `Ctrl+Shift+B`
3. Select "Backend: Dev Server"
4. Backend starts in terminal

### Method 2: Using Debug

1. Press `F5`
2. Select "FastAPI: Debug Backend"
3. Backend starts with debugger attached

### Method 3: Multiple Terminals in VS Code

1. Open VS Code
2. Press `Ctrl+Shift+`` (backtick) to open terminal
3. Split terminal: Click "+" icon → "Split Terminal"
4. Run each service in separate terminal panel

---

## Troubleshooting

### "PostgreSQL is missing the pgvector extension"

**Check if pgvector is installed:**
```powershell
psql -U postgres -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

**If no results, install pgvector:**
```powershell
# Download from: https://github.com/pgvector/pgvector/releases
# Run the installer, then:
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### "Redis connection refused"

**Check if Redis is running:**
```powershell
redis-cli ping
# Should return: PONG
```

**Start Redis if not running:**
```powershell
# If installed as service:
net start redis

# Or run directly:
redis-server
```

### "Port 8000 already in use"

**Find what's using the port:**
```powershell
netstat -ano | findstr :8000
```

**Kill the process:**
```powershell
taskkill /PID <PID> /F
```

**Or use a different port:**
```powershell
uvicorn bugsift.main:app --host 0.0.0.0 --port 8001 --reload --app-dir src
```

### "Database connection error"

**Check PostgreSQL is running:**
```powershell
psql -U postgres -c "SELECT 1;"
```

**Check credentials in .env:**
```powershell
# Make sure these match your PostgreSQL installation:
POSTGRES_USER=postgres
POSTGRES_PASSWORD=sumanth123  # Change to your actual password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### "Module not found: bugsift.main"

**Make sure you're in the backend directory:**
```powershell
cd E:\Bug Sift\bugsift\backend
```

**Make sure venv is activated:**
```powershell
.\venv\Scripts\activate
```

**Verify the module exists:**
```powershell
ls src/bugsift/main.py
```

---

## Accessing pgAdmin (Database Management)

Since you're not using Docker, install pgAdmin separately:

1. **Download pgAdmin:**
   - Visit https://www.pgadmin.org/download/
   - Download for Windows
   - Install

2. **Add Server Connection:**
   - Open pgAdmin
   - Right-click "Servers" → "Create" → "Server"
   - **General tab:**
     - Name: `bugsift-local`
   - **Connection tab:**
     - Host: `localhost`
     - Port: `5432`
     - Username: `postgres`
     - Password: `sumanth123` (your password)
   - Click "Save"

3. **Browse your database:**
   - Expand "Servers" → "bugsift-local" → "Databases" → "bugsift"
   - You can now view tables, run queries, etc.

---

## Stopping Services

### Stop Backend
- Press `Ctrl+C` in the backend terminal

### Stop Frontend
- Press `Ctrl+C` in the frontend terminal

### Stop Redis
```powershell
redis-cli shutdown
# Or if running as service:
net stop redis
```

### Stop PostgreSQL
```powershell
# Usually runs as service, stop if needed:
net stop postgresql-x64-15
```

---

## Quick Reference Card

Save this for quick access:

```powershell
# START EVERYTHING
# Terminal 1: PostgreSQL (usually auto-starts as service)
net start postgresql-x64-15

# Terminal 2: Redis
redis-server

# Terminal 3: Backend
cd E:\Bug Sift\bugsift\backend
.\venv\Scripts\activate
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src

# Terminal 4: Frontend (optional)
cd E:\Bug Sift\bugsift\frontend
npm run dev

# TEST
curl http://localhost:8000/api/health
start http://localhost:8000/docs

# STOP
# Backend: Ctrl+C
# Frontend: Ctrl+C
# Redis: redis-cli shutdown
```

---

## Next Steps

Once everything is running:
1. Open http://localhost:8000/docs to see API documentation
2. Open http://localhost:3000 for the dashboard (if frontend is running)
3. Follow the onboarding guide to set up GitHub App
4. Add your LLM API key in the dashboard settings

**Need help?** Check the main `GETTING_STARTED.md` file in the bugsift folder.