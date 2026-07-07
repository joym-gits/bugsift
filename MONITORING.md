# bugsift v0.2.0 — Monitoring & Observability

This guide covers monitoring, observability, and alerting for production deployments.

## Quick Start

### Container Health Checks

All services include built-in health checks:

```bash
# Check service status
docker compose ps

# Expected output:
# STATUS: Up X seconds (healthy)
```

### Real-Time Monitoring

```bash
# Watch container resource usage
docker stats bugsift-backend-1 bugsift-postgres-1 bugsift-redis-1

# Watch logs in real-time
docker compose logs -f backend
docker compose logs -f postgres
docker compose logs -f redis
```

---

## Monitoring Services

### Backend (FastAPI)

**Key Metrics:**
- Request latency (p50, p95, p99)
- Error rate (4xx, 5xx responses)
- Active connections
- Worker process count

**Health Check Endpoint:**
```bash
curl http://localhost:8001/health
```

**Log Location:**
```bash
docker compose logs backend
```

**What to monitor:**
- `Application startup complete` — app is ready
- `ERROR` — indicates failures
- `WARNING` — potential issues

### PostgreSQL Database

**Key Metrics:**
- Connection count (active vs. max)
- Query latency
- Disk usage
- Cache hit ratio
- Lock contention

**Health Check:**
```bash
docker compose exec postgres pg_isready -U postgres
```

**Monitor with:**
```bash
# Inside container
docker compose exec postgres psql -U postgres -c "SELECT * FROM pg_stat_activity;"
docker compose exec postgres psql -U postgres -c "SELECT datname, size FROM pg_database_size(datname);"
```

**What to monitor:**
- Connection limit approaching (default: 100)
- Disk usage > 80%
- Long-running queries (> 30s)

### Redis Cache

**Key Metrics:**
- Memory usage
- Hit/miss ratio
- Key count
- Eviction rate

**Health Check:**
```bash
docker compose exec redis redis-cli ping
# Expected: PONG
```

**Monitor with:**
```bash
docker compose exec redis redis-cli info stats
docker compose exec redis redis-cli info memory
```

**What to monitor:**
- Memory usage > 80% of available
- Eviction rate increasing
- Command failures

### Nginx Reverse Proxy

**Key Metrics:**
- Request rate
- Error rate (4xx, 5xx)
- Response time
- Active connections

**Check:**
```bash
docker compose logs nginx
```

**What to monitor:**
- `upstream timed out` — backend not responding
- `502 Bad Gateway` — backend down
- Connection refused — upstream not available

---

## Production Monitoring Setup

### Option 1: Host Metrics (Linux)

**Install monitoring tools:**
```bash
# CPU, memory, disk
apt-get install sysstat

# View CPU usage
mpstat 1 10

# View memory
free -h

# View disk
df -h
```

### Option 2: Docker Stats (Simple)

```bash
# Export to CSV every 10 seconds
watch -n 10 'docker stats --no-stream --format "{{.Container}},{{.CPUPerc}},{{.MemUsage}}" > docker-stats.csv'
```

### Option 3: Prometheus + Grafana (Recommended)

**Add to docker-compose.yml:**
```yaml
prometheus:
  image: prom/prometheus:latest
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
    - prometheus_data:/prometheus
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'

grafana:
  image: grafana/grafana:latest
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
  volumes:
    - grafana_data:/var/lib/grafana
```

**prometheus.yml:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['localhost:9323']
  
  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']
  
  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']
```

---

## Key Metrics to Monitor

### Critical (Set alerts on these)

| Metric | Threshold | Action |
|--------|-----------|--------|
| Backend down | N/A | Page on-call immediately |
| Database connection limit | > 90% | Scale up or investigate connections |
| Disk usage | > 95% | Add disk space or archive old data |
| Error rate | > 5% over 5m | Check logs, investigate |
| Request latency p99 | > 10s | Profile backend, check DB |

### Important (Monitor regularly)

| Metric | Threshold | Action |
|--------|-----------|--------|
| Memory usage | > 80% | Check for leaks, restart if needed |
| Disk usage | > 80% | Plan expansion |
| Redis eviction | Any | Increase memory or reduce TTL |
| DB query latency | > 2s | Add indexes, optimize query |
| CPU usage | > 80% sustained | Scale horizontally or optimize |

### Informational (Track for trends)

- Request count (throughput)
- Cache hit ratio
- Active user sessions
- Data size growth

---

## Alerting Rules

### Email/Slack Alerts

**Using a monitoring tool (Prometheus + AlertManager):**

```yaml
groups:
  - name: bugsift
    interval: 30s
    rules:
      - alert: BackendDown
        expr: up{job="backend"} == 0
        for: 2m
        annotations:
          summary: "Backend is down"
      
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"
      
      - alert: DiskFull
        expr: node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.05
        for: 10m
        annotations:
          summary: "Disk > 95% full"
```

**Using Docker events:**
```bash
# Simple: Run a script that checks health every minute
*/1 * * * * /opt/bugsift/health-check.sh
```

**health-check.sh:**
```bash
#!/bin/bash
if ! curl -f http://localhost:8001/health > /dev/null 2>&1; then
  echo "ALERT: Backend down at $(date)" | mail -s "bugsift Alert" ops@company.com
fi
```

---

## Logging Strategy

### Log Levels

- **ERROR** — Something failed. Investigate immediately.
- **WARNING** — Potential issue. Check soon.
- **INFO** — Normal operation. Good for tracing requests.
- **DEBUG** — Detailed info. Enable only for troubleshooting.

### Log Aggregation

**Using ELK Stack (Elasticsearch + Logstash + Kibana):**

1. Ship Docker logs to Logstash
2. Parse with Logstash
3. Store in Elasticsearch
4. Query/visualize in Kibana

**Using Cloud Logging:**

- AWS CloudWatch: `docker logs` auto-shipped to CloudWatch
- GCP Cloud Logging: Configure Docker daemon to ship to GCP
- Azure Monitor: Similar setup

**Local log rotation:**
```bash
# In docker-compose.yml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "10"
```

---

## Performance Baselines

After deployment, establish baselines for your environment:

```bash
# Capture baseline metrics
docker stats --no-stream > baseline-$(date +%s).txt
```

**Expected Performance (single-node, 2GB RAM):**

| Metric | Expected | Warning | Critical |
|--------|----------|---------|----------|
| Backend response time (p50) | < 100ms | > 500ms | > 2s |
| Backend response time (p99) | < 1s | > 3s | > 10s |
| Database query time (p50) | < 50ms | > 200ms | > 1s |
| Error rate | < 0.1% | > 1% | > 5% |
| Memory usage | 800MB-1.2GB | > 1.5GB | > 1.8GB |
| CPU usage | 10-30% | > 60% | > 90% |

---

## Troubleshooting via Logs

### Backend Crashes on Startup

```bash
docker compose logs backend | grep -i "error\|exception"
```

**Common causes:**
- Database connection failed → Check DATABASE_URL
- Missing environment variables → Check .env file
- Port already in use → Check `lsof -i :8001`

### Slow Requests

```bash
docker compose logs backend | grep "duration"
```

**Check:**
1. Database performance: `docker compose exec postgres psql -c "SELECT * FROM pg_stat_statements;"`
2. Network latency: `ping your-domain.com`
3. Disk I/O: `docker stats postgres`

### Memory Leak Detection

```bash
# Monitor memory over time
watch -n 5 'docker stats --no-stream | grep backend'
```

**If memory keeps growing:**
1. Restart container: `docker compose restart backend`
2. Check application logs for unfreed resources
3. Profile with Python profiler (if needed)

### Database Connection Issues

```bash
# Check active connections
docker compose exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# Check for idle connections
docker compose exec postgres psql -U postgres -c "SELECT * FROM pg_stat_activity WHERE state='idle';"
```

---

## Maintenance Windows

### Recommended Monitoring During Maintenance

Before upgrading or restarting:

```bash
# Monitor upgrade process
docker compose logs -f backend &
watch -n 1 'docker compose ps'
```

**Success indicators:**
- All containers reach `Up` status
- No `ERROR` in logs
- Health check returns 200

---

## Next Steps

1. **Deploy monitoring tool** (Prometheus/Grafana or cloud equivalent)
2. **Set up alerting** (PagerDuty, OpsGenie, or email)
3. **Create runbook** for on-call engineers
4. **Regular reviews** — check dashboards weekly
5. **Capacity planning** — track growth trends monthly

See [SLA.md](SLA.md) for response time expectations and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues.
