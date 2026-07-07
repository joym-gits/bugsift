# Quick Start: Running bugsift Backend Locally

## Prerequisites
- Python 3.11+ (you have 3.13 ✓)
- PostgreSQL with pgvector extension
- Redis
- Virtual environment activated (you have this ✓)

## Option 1: Docker Compose (RECOMMENDED - 2 minutes)

This is the easiest way since pgvector is already configured in Docker.

```powershell
# From bugsift root directory
cd E:\Bug Sift\bugsift

# Start all services
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Verify services are running
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps

# Run migrations
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head

# View backend logs
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend

# Access points:
# - Backend API: http://localhost:8000
# - Dashboard: http://localhost:8080
# - pgAdmin: http://localhost:5050 (admin@bugsift.local / admin)
```

## Option 2: Install pgvector on Local PostgreSQL

### Step 1: Install pgvector

**Using Chocolatey (easiest):**
```powershell
choco install pgvector
```

**Or download installer:**
1. Visit https://github.com/pgvector/pgvector/releases
2. Download the Windows installer for PostgreSQL 15 or 16
3. Run the installer

**Or build from source:**
```powershell
# Install Visual Studio Build Tools first if needed
# Then:
git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git
cd pgvector
$env:PGROOT = "C:\Program Files\PostgreSQL\15"  # Adjust to your version
make
make install
```

### Step 2: Enable pgvector in your database

```powershell
# Connect to PostgreSQL
psql -U postgres -d bugsift

# In psql console:
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

### Step 3: Run migrations

```powershell
cd E:\Bug Sift\bugsift\backend
alembic upgrade head
```

### Step 4: Start the backend

```powershell
# Make sure Redis is running (install Redis for Windows or use Docker)
# Then start the backend:
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

## Option 3: Use Docker for PostgreSQL + Redis only

Run just the database services in Docker, and backend locally:

```powershell
# From bugsift root
cd E:\Bug Sift\bugsift

# Start only database services
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis

# Wait for PostgreSQL to be ready (check with docker compose ps)

# Run migrations
cd backend
alembic upgrade head

# Start backend locally
uvicorn bugsift.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

## Troubleshooting

### "PostgreSQL is missing the pgvector extension"
- Use Option 1 (Docker Compose) - it's already configured
- Or install pgvector locally using Option 2

### "Redis connection refused"
- Install Redis for Windows: https://github.com/microsoftarchive/redis/releases
- Or use Docker: `docker run -d -p 6379:6379 redis:7-alpine`
- Or use Option 1 (Docker Compose includes Redis)

### "Port 8000 already in use"
```powershell
# Use a different port
uvicorn bugsift.main:app --host 0.0.0.0 --port 8001 --reload --app-dir src
```

## VS Code Quick Start

1. Open `E:\Bug Sift\bugsift` in VS Code
2. Press `Ctrl+Shift+B`
3. Select "Docker Compose: Up"
4. Wait for services to start
5. Press `F5` and select "FastAPI: Debug Backend"
6. Or use "Open pgAdmin in Browser" to manage your database

## Verify Installation

```powershell
# Test backend health
curl http://localhost:8000/api/health

# Should return: {"status":"ok","version":"0.x.x"}
```

## Next Steps

Once backend is running:
1. Open http://localhost:8080 for the dashboard
2. Open http://localhost:5050 for pgAdmin
3. Follow the onboarding guide to register GitHub App
4. Add your LLM API key in Settings
5. Install on a test repository