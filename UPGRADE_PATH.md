# bugsift — Upgrade Guide

This guide covers upgrading bugsift between versions.

---

## Quick Start

### For Most Users: Automated Upgrade

```bash
# Backup first (always!)
docker compose exec postgres pg_dump -U postgres bugsift > backup_$(date +%s).sql

# Pull latest images
docker compose pull

# Run migrations
docker compose run --rm backend alembic upgrade head

# Restart services
docker compose restart

# Verify
docker compose ps
curl http://localhost:8001/health
```

---

## Version-Specific Guides

### Upgrading from v0.1.0 → v0.2.0

This is a **non-breaking upgrade** with schema changes.

#### What's New
- SAST/security scanning in CI/CD
- Code coverage enforcement
- Audit logging
- RBAC (roles)
- Enhanced monitoring
- Multi-architecture builds

#### Compatibility
- ✅ All v0.1.0 data preserved
- ✅ Existing GitHub App works
- ✅ LLM keys/config work
- ⚠️ Requires new env variables

#### Step-by-Step

**1. Backup your data:**
```bash
docker compose exec postgres pg_dump -U postgres bugsift > backup_v0.1_$(date +%s).sql

# Or backup the entire volume
docker run --rm -v bugsift_postgres_data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/postgres_backup.tar.gz -C /data .
```

**2. Review new environment variables:**
```bash
# Compare your .env with defaults
diff .env .env.example

# New variables to add:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001  # or your domain
LOG_LEVEL=info                                   # optional
SESSION_TIMEOUT=43200                            # 12 hours
```

**3. Stop the current deployment:**
```bash
docker compose down
```

**4. Update to v0.2.0:**
```bash
# Option A: Use new installer
BUGSIFT_IMAGE_TAG=v0.2.0 curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.2.0/install.sh | bash

# Option B: Manual update
BUGSIFT_IMAGE_TAG=v0.2.0 docker compose pull
```

**5. Run migrations:**
```bash
docker compose run --rm backend alembic upgrade head
```

Expected output:
```
[alembic.runtime.migration] Running upgrade  -> xxxxx, Create audit_log table
[alembic.runtime.migration] Running upgrade xxxxx -> xxxxx, Add role column to User
```

**6. Start the new deployment:**
```bash
docker compose up -d
```

**7. Verify:**
```bash
# Check services are running
docker compose ps

# Check logs for errors
docker compose logs backend | grep -i "error\|exception"

# Test API
curl http://localhost:8001/health
curl http://localhost:3001/
```

#### Database Changes

| Table | Changes | Data Impact |
|-------|---------|------------|
| `audit_log` | NEW | No data loss (new table) |
| `User` | +role column | Existing users get 'viewer' role |
| `TriageCard` | +feedback column | Existing cards unaffected |
| (others) | No change | No migration needed |

**Verify migrations completed:**
```bash
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM alembic_version;"
```

---

## Patch Upgrades (v0.2.x)

### v0.2.0 → v0.2.1

These are **always backward-compatible** (bug fixes, security patches).

```bash
# Simple restart with new images
docker compose pull
docker compose up -d

# No migrations needed for patch releases
```

**When to upgrade patches:**
- ✅ Security patches: immediately
- ✅ Critical bugs: within 1 week
- ✅ Minor bugs: at your convenience

---

## Before Any Upgrade

### Checklist

- [ ] Read release notes at `CHANGELOG.md`
- [ ] Backup database: `docker compose exec postgres pg_dump`
- [ ] Backup volumes: `docker run --rm -v X:/data -v $(pwd):/backup ubuntu tar czf /backup/backup.tar.gz -C /data .`
- [ ] Test upgrade in staging first
- [ ] Notify users of potential downtime
- [ ] Have rollback plan ready

### Backup Strategy

**Full backup before upgrade:**
```bash
#!/bin/bash
BACKUP_DIR="/backups/bugsift_$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

# Database
docker compose exec postgres pg_dump -U postgres bugsift > "$BACKUP_DIR/database.sql"

# Volumes
for volume in postgres_data redis_data; do
  docker run --rm \
    -v bugsift_${volume}:/data \
    -v "$BACKUP_DIR:/backup" \
    ubuntu tar czf "/backup/${volume}.tar.gz" -C /data .
done

# Configuration
cp .env "$BACKUP_DIR/.env.backup"

echo "Backup complete: $BACKUP_DIR"
```

---

## After Upgrade

### Post-Upgrade Verification

```bash
# 1. Check all services are healthy
docker compose ps

# Expected:
# - backend: Up (healthy)
# - frontend: Up
# - postgres: Up (healthy)
# - redis: Up (healthy)

# 2. Check logs for errors
docker compose logs --tail 50

# 3. Test core functionality
curl http://localhost:8001/health
curl http://localhost:3001/

# 4. Verify database
docker compose exec postgres psql -U postgres -c "SELECT version();"

# 5. Check audit log created
docker compose exec postgres psql -U postgres -c "SELECT COUNT(*) FROM audit_log;"
```

### Common Post-Upgrade Issues

#### Frontend Shows Blank Page

**Cause:** Old cache or missing API URL

**Fix:**
```bash
# Hard refresh in browser: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
# Or clear browser cache and reload

# Verify API_BASE_URL
docker compose logs frontend | grep -i "api"
```

#### 500 Errors in Backend

**Cause:** Migration failed or incomplete

**Fix:**
```bash
# Check migration status
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM alembic_version;"

# Retry migration
docker compose run --rm backend alembic upgrade head

# Check for errors
docker compose logs backend | grep -i "error"
```

#### Database Connection Issues

**Cause:** Schema incompatibility or password changed

**Fix:**
```bash
# Verify DATABASE_URL
grep DATABASE_URL .env

# Test connection
docker compose exec postgres pg_isready -U postgres

# Restart postgres
docker compose restart postgres
```

---

## Rollback Procedure

**If something goes wrong, rollback to previous version:**

### Option 1: From Backup (Recommended)

```bash
# 1. Stop current version
docker compose down

# 2. Restore database backup
docker compose up -d postgres
docker compose exec postgres psql -U postgres < backup_v0.1_12345.sql

# 3. Restore old images
docker compose down
BUGSIFT_IMAGE_TAG=v0.1.0 docker compose pull
docker compose up -d

# 4. Verify
docker compose ps
curl http://localhost:8001/health
```

### Option 2: Downgrade Images Only

```bash
# Update docker-compose.yml to reference v0.1.0 images
# Or use environment variable:
BUGSIFT_IMAGE_TAG=v0.1.0 docker compose up -d

# Note: This only works if database is compatible with old version
```

### Option 3: From Volume Backup

```bash
# Stop all containers
docker compose down

# Remove corrupted volume
docker volume rm bugsift_postgres_data

# Restore from backup
docker run --rm -v bugsift_postgres_data:/data -v $(pwd):/backup \
  ubuntu tar xzf /backup/postgres_backup.tar.gz -C /data

# Start with old version
BUGSIFT_IMAGE_TAG=v0.1.0 docker compose up -d
```

---

## Upgrading in Production

### Zero-Downtime Strategy

For production deployments with multiple instances:

**Setup:**
```
Load Balancer (Nginx)
    ↓
    ├─ Instance A (v0.1.0)
    ├─ Instance B (v0.1.0)
    └─ Instance C (v0.1.0)
          ↓
      Shared Database
```

**Upgrade process:**

```bash
# 1. Drain traffic from Instance A (remove from load balancer)
# 2. Upgrade Instance A to v0.2.0
#    docker compose pull && docker compose up -d
# 3. Verify Instance A works
# 4. Repeat for Instances B and C
# 5. Run single migration on shared database (once)
#    docker compose run --rm backend alembic upgrade head
# 6. Add all instances back to load balancer
# 7. Verify traffic flows to all instances
```

**Total downtime:** ~2 minutes (during final migration)

---

## Upgrade Troubleshooting

### Migration Hangs

**Symptom:** `alembic upgrade head` takes > 5 minutes

**Cause:** Lock on large table or slow disk

**Fix:**
```bash
# Check for locks
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM pg_locks WHERE NOT granted;"

# Kill blocking query
docker compose exec postgres psql -U postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='active';"

# Retry migration
docker compose run --rm backend alembic upgrade head
```

### Migration Fails

**Symptom:** Migration errors with "column does not exist"

**Cause:** Partial migration or concurrent edit

**Fix:**
```bash
# Check current version
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM alembic_version;"

# Reset to known state (if safe)
docker compose exec postgres psql -U postgres -c \
  "DELETE FROM alembic_version;"

# Restore from backup and retry
# (safer than trying to fix manually)
```

### Image Pull Fails

**Symptom:** `docker compose pull` returns 401/403

**Cause:** GitHub Container Registry authentication

**Fix:**
```bash
# Log in to GHCR
docker login ghcr.io

# Try again
docker compose pull
```

---

## Keeping Up to Date

### Check for Updates

```bash
# View your current version
docker compose ps | grep backend

# Check latest available
curl -s https://api.github.com/repos/joym-gits/bugsift/releases | jq '.[0].tag_name'

# Or visit: https://github.com/joym-gits/bugsift/releases
```

### Update Notifications

Enable update checks:

```bash
# Add to crontab (weekly check)
0 0 * * 0 curl -s https://api.github.com/repos/joym-gits/bugsift/releases | jq '.[0].tag_name' > /tmp/bugsift_latest.txt
```

---

## Version Support

| Version | Release | EoL | Status |
|---------|---------|-----|--------|
| 0.2.x | 2026-07-07 | 2026-12-07 | Current |
| 0.1.x | 2026-06-01 | 2026-09-01 | Maintenance |
| 0.0.x | N/A | N/A | Unsupported |

**Support Policy:**
- Current version: 6 months of updates
- Maintenance: 3 months of critical patches
- End of Life: No support

---

## Migration from v0.1.0 Database

### Database Schema Changes

**Auto-applied by alembic:**

```sql
-- Create audit_log table
CREATE TABLE audit_log (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR NOT NULL,
  action VARCHAR NOT NULL,
  resource VARCHAR,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR,
  result VARCHAR,
  details JSONB
);

-- Add role column to User
ALTER TABLE "User" ADD COLUMN role VARCHAR DEFAULT 'viewer';

-- Add feedback column to TriageCard
ALTER TABLE triage_card ADD COLUMN feedback JSONB;
```

**Data migration:**

```sql
-- Set existing users to 'triager' (they can triage)
UPDATE "User" SET role = 'triager' WHERE id IS NOT NULL;

-- Grant first admin user 'admin' role
UPDATE "User" SET role = 'admin' WHERE email = 'your-email@example.com';
```

---

## Questions?

- **Upgrade fails?** See Troubleshooting section above
- **Data loss?** Always have backups; see Backup Strategy
- **Need help?** See [SLA.md](SLA.md) for support options

See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.
