# bugsift v0.2.0 — Troubleshooting Guide

This guide covers common issues, diagnostics, and solutions.

---

## Startup Issues

### Backend Won't Start

**Error:** `docker compose logs backend` shows errors

**Diagnostic:**
```bash
# Check logs for specific error
docker compose logs backend | grep -i "error\|failed\|exception"

# Check if port is in use
lsof -i :8001

# Verify environment variables
docker compose exec backend env | grep BUGSIFT
```

**Common causes & fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `no such file` (alembic) | Missing migration files | `git checkout alembic/` |
| `Connection refused` (postgres) | Database not ready | Wait 30s, then retry |
| `Address already in use` | Port 8001 occupied | `lsof -i :8001` and kill process |
| `ModuleNotFoundError` | Package not installed | `pip install -e .` inside container |
| `OperationalError: FATAL` | Wrong DATABASE_URL | Check .env file |

### Database Won't Start

**Error:** `docker compose logs postgres` shows errors

**Diagnostic:**
```bash
# Check postgres logs
docker compose logs postgres | tail -50

# Verify volume exists
docker volume ls | grep bugsift

# Check disk space
df -h
```

**Common causes & fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `FATAL: could not create shared memory segment` | Disk full | `df -h`, add space |
| `could not open relation` | Corrupted data | Restore from backup |
| `FATAL: password authentication failed` | Wrong password in .env | Update DATABASE_URL |
| `FATAL: cannot create lock file` | Permission issue | `docker compose down && docker compose up` |

### Redis Won't Start

**Error:** `docker compose logs redis` shows errors

**Diagnostic:**
```bash
# Check redis logs
docker compose logs redis | tail -20

# Verify redis is responding
docker compose exec redis redis-cli ping
```

**Common causes & fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `Permission denied` | Volume ownership | `sudo chown 1000:1000 redis_data` |
| `Bad file descriptor` | Corrupted data | Delete volume, restart |
| Port conflict | Another redis running | Kill other instance |

---

## Runtime Issues

### Backend Running But Returns 500 Errors

**Error:** `curl http://localhost:8001/` returns 500

**Diagnostic:**
```bash
# Check backend logs for errors
docker compose logs backend | grep -i "error\|exception\|traceback" | tail -20

# Check database connection
docker compose exec backend python -c "from sqlalchemy import create_engine; engine = create_engine(os.getenv('DATABASE_URL')); print(engine.execute('SELECT 1'))"

# Check LLM key is valid
docker compose logs backend | grep -i "anthropic\|openai" | head -5
```

**Common causes & fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `DatabaseError` | DB connection failed | Check DATABASE_URL, restart postgres |
| `HTTPError 401` (LLM) | Invalid API key | Update LLM_KEY in settings |
| `RuntimeError: Event loop closed` | Async issue | Restart backend: `docker compose restart backend` |
| `ImportError: No module named` | Package missing | Rebuild image: `docker-compose build --no-cache backend` |

### Frontend Shows Blank Page

**Error:** Browser shows blank/error page at localhost:3001

**Diagnostic:**
```bash
# Check frontend logs
docker compose logs frontend | tail -30

# Check if it's a build issue
docker compose logs frontend | grep -i "build\|next"

# Test frontend directly
curl -s http://localhost:3001/ | head -c 500

# Check API connectivity
curl http://localhost:8001/docs
```

**Common causes & fixes:**

| Issue | Cause | Fix |
|-------|-------|-----|
| Blank page | API unreachable | Check NEXT_PUBLIC_API_BASE_URL in .env |
| JavaScript errors | Build failed | Restart: `docker compose restart frontend` |
| CSS not loading | Static files missing | Rebuild frontend |
| "Failed to fetch" | CORS issue | Check backend CORS settings |

### Triage Cards Not Appearing

**Error:** Issues created but no triage cards show up

**Diagnostic:**
```bash
# Check if webhook is receiving events
docker compose logs backend | grep -i "webhook\|github"

# Check database for cards
docker compose exec postgres psql -U postgres -c \
  "SELECT COUNT(*) FROM triage_card;"

# Check worker is running
docker compose ps worker

# Check worker logs
docker compose logs worker | tail -30
```

**Common causes & fixes:**

| Issue | Cause | Fix |
|-------|-------|-----|
| No webhook events | GitHub App not installed | Go to GitHub App → Install on repo |
| LLM key missing | Never added key | Add key in Settings |
| Worker down | Service crashed | `docker compose restart worker` |
| Database full | No disk space | Check `df -h` |
| Webhook forwarding | Using localhost without smee | Update webhook URL in GitHub |

---

## Performance Issues

### Slow Response Times

**Symptom:** Triage takes 30+ seconds per issue (target: 6-10s)

**Diagnostic:**
```bash
# Check resource usage
docker stats

# Check database query performance
docker compose logs backend | grep -i "database\|query" | tail -10

# Check LLM latency
docker compose logs backend | grep -i "anthropic\|openai" | grep "took"

# Check for slow queries
docker compose exec postgres psql -U postgres -c \
  "SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 5;"
```

**Common causes & fixes:**

| Cause | Indicator | Fix |
|-------|-----------|-----|
| CPU maxed out | `docker stats` shows CPU > 90% | Upgrade instance size |
| RAM constrained | Memory > 80% | Add RAM or reduce concurrency |
| Slow LLM provider | Triage latency > 20s | Try different provider (Anthropic vs OpenAI) |
| Database slow | Queries > 1s | Add index: `CREATE INDEX idx_repo_id ON triage_card(repo_id);` |
| Network latency | Timeouts to LLM | Check network connectivity |

### Memory Leak

**Symptom:** Memory usage keeps growing, crashes over time

**Diagnostic:**
```bash
# Monitor memory over time
watch -n 5 'docker stats --no-stream backend'

# Check for resource leaks
docker compose logs backend | grep -i "resource\|leak\|memory"

# Inspect backend process
docker exec bugsift-backend-1 ps aux | grep gunicorn
```

**Common causes & fixes:**

| Cause | Fix |
|-------|-----|
| Application bug | Restart container: `docker compose restart backend` |
| Unfreed connections | Check database pool settings |
| Large cache buildup | Clear Redis: `docker compose exec redis redis-cli FLUSHDB` |
| Python garbage collection | Force cleanup: `docker exec bugsift-backend-1 python -c "import gc; gc.collect()"` |

---

## Database Issues

### Database Connection Limit Reached

**Error:** `FATAL: sorry, too many clients already`

**Diagnostic:**
```bash
# Check current connections
docker compose exec postgres psql -U postgres -c \
  "SELECT count(*) as connections FROM pg_stat_activity;"

# See who's connected
docker compose exec postgres psql -U postgres -c \
  "SELECT usename, application_name, state FROM pg_stat_activity WHERE state != 'idle';"
```

**Fix:**
```bash
# Increase limit in docker-compose.yml
postgres:
  environment:
    POSTGRES_INIT_ARGS: "-c max_connections=200"

# Or dynamically:
docker compose exec postgres psql -U postgres -c \
  "ALTER SYSTEM SET max_connections = 200;"
docker compose exec postgres pg_ctl reload
```

### Database Growing Too Large

**Error:** Disk space low, database consuming 80%+

**Diagnostic:**
```bash
# Check database size
docker compose exec postgres psql -U postgres -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database_size(datname) > 0 ORDER BY pg_database_size(datname) DESC;"

# Check table sizes
docker compose exec postgres psql -U postgres -c \
  "SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename)) FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(tablename) DESC;"
```

**Fix:**
```bash
# Archive old triage decisions (> 2 years)
docker compose exec postgres psql -U postgres -c \
  "DELETE FROM triage_card WHERE created_at < now() - interval '2 years';"

# Vacuum to reclaim space
docker compose exec postgres vacuumdb -U postgres
```

### Corrupted Database

**Error:** `FATAL: could not open relation` or similar

**Diagnostic:**
```bash
# Check PostgreSQL logs
docker compose logs postgres | grep -i "corruption\|fatal"

# Try to backup corrupted data
docker compose exec postgres pg_dumpall > dump_before_recovery.sql
```

**Fix:**

**Option 1: Restore from Backup**
```bash
# List available backups
ls -lh backup_*.sql

# Restore
docker compose exec postgres psql < backup_2026_06_01.sql
```

**Option 2: Rebuild Volume**
```bash
# Warning: Data loss!
docker compose down
docker volume rm bugsift_postgres_data
docker compose up -d postgres
```

---

## GitHub Integration Issues

### Webhook Not Triggering

**Error:** Issues created but no triage events received

**Diagnostic:**
```bash
# Check GitHub App installation
curl -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/user/installations

# Check webhook deliveries in GitHub
# Settings → Developer settings → GitHub Apps → [Your App] → Advanced → Recent Deliveries

# Check bugsift logs
docker compose logs backend | grep -i "webhook\|issue.opened"
```

**Fix:**

1. **Re-install the GitHub App:**
   - Go to your GitHub App settings
   - Delete and reinstall on the repository
   - Verify permissions in `.env`

2. **Check webhook URL:**
   - If using localhost: Verify smee.io is configured
   - If using domain: Verify DNS resolves

3. **Verify GitHub App credentials:**
   ```bash
   docker compose exec backend python -c \
     "from bugsift.github import config; print(config.get_app_id())"
   ```

### GitHub API Rate Limit Exceeded

**Error:** `API rate limit exceeded` in logs

**Diagnostic:**
```bash
# Check current rate limit
curl -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/rate_limit | jq '.'
```

**Fix:**

```bash
# Use a personal token with higher limits
# https://github.com/settings/tokens → Create new token
# Grant: repo, read:org

# Update in Settings → GitHub App
```

---

## LLM Provider Issues

### OpenAI API Key Invalid

**Error:** `401 Unauthorized` or `Invalid API key`

**Diagnostic:**
```bash
# Test the key directly
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_KEY"
```

**Fix:**
1. Generate new key: https://platform.openai.com/api-keys
2. Update in Settings → LLM Provider

### Anthropic Quota Exceeded

**Error:** `RateLimitError` or `OverloadedError`

**Diagnostic:**
```bash
# Check usage
docker compose logs backend | grep -i "anthropic\|quota"
```

**Fix:**
1. Check usage in Anthropic console
2. Increase spending limit or wait for reset
3. Or switch to OpenAI/Google

### Ollama Connection Failed

**Error:** `Connection refused` or `Network error`

**Diagnostic:**
```bash
# Test Ollama is running
curl http://localhost:11434/api/tags

# Check if model is available
curl http://localhost:11434/api/pull -X POST -d '{"name":"llama2"}'
```

**Fix:**
1. Start Ollama: `ollama serve`
2. Verify model installed: `ollama list`
3. Check firewall allows port 11434

---

## Monitoring & Logging

### How to Get Detailed Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f postgres

# With timestamps
docker compose logs -f --timestamps backend

# Last 100 lines
docker compose logs -f --tail 100 backend

# Since specific time
docker compose logs -f --since 2026-07-07T10:00:00Z backend
```

### Enable Debug Logging

```bash
# In docker-compose.yml, set environment:
backend:
  environment:
    LOG_LEVEL: DEBUG
    PYTHONUNBUFFERED: 1

# Restart
docker compose restart backend

# View debug logs
docker compose logs -f backend | grep DEBUG
```

### Check System Resources

```bash
# Real-time stats
docker stats

# Memory usage
free -h

# Disk usage
df -h

# CPU usage
mpstat 1 10

# Network
netstat -tlnp
```

---

## Escalation

### Still Stuck?

1. **Check GitHub Issues:** https://github.com/joym-gits/bugsift/issues
2. **Review logs completely:**
   ```bash
   docker compose logs > debug_logs.txt
   # Attach to issue
   ```
3. **Provide context:**
   - Deployment size (repos, issues/day)
   - Version: `cat docker-compose.yml | grep image`
   - Error: Exact error message
   - Steps to reproduce
   - Expected vs actual behavior

### Getting Help

- **Documentation:** See [MONITORING.md](MONITORING.md), [SLA.md](SLA.md)
- **Deployment guide:** See [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)
- **Performance guide:** See [PERFORMANCE.md](PERFORMANCE.md)
- **GitHub Issues:** Create new issue with full logs

---

## Preventive Maintenance

### Daily
- Monitor resource usage
- Check for errors in logs

### Weekly
- Review triage accuracy
- Check database size

### Monthly
- Rotate API tokens
- Update Docker images
- Test backup/restore
- Review audit logs

### Quarterly
- Full security audit
- Capacity planning review
- Performance benchmarking

---

## Common Fixes Quick Reference

| Problem | Quick Fix |
|---------|-----------|
| Container crashed | `docker compose restart [service]` |
| Out of disk space | `docker system prune -a` |
| Memory leak | Restart backend + check logs |
| Database locked | `docker compose restart postgres` |
| Slow performance | Check `docker stats` |
| Webhook not working | Re-install GitHub App |
| Blank dashboard | Check browser console (F12) |
| No triage cards | Check LLM key is set |
| 500 errors | Check logs: `docker compose logs backend` |

See [MONITORING.md](MONITORING.md) for comprehensive monitoring guidance.
