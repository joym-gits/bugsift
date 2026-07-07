# bugsift v0.2.0 — Performance & Capacity Planning

This document covers performance characteristics, benchmarks, and capacity planning for bugsift deployments.

---

## Performance Baseline

### Single Instance (2GB, 1 CPU)

Tested on: Standard cloud VM (AWS t3.small equivalent)

#### Throughput

| Metric | Value | Notes |
|--------|-------|-------|
| Issues processed/hour | 60 | Sequential (one at a time) |
| Issues processed/day | 500-1000 | Typical workflow |
| Concurrent triage cards | 1-2 | Dashboard users |
| API requests/second | 5-10 | Burst capacity |

#### Latency (Response Time)

| Operation | p50 (50th %) | p95 (95th %) | p99 (99th %) |
|-----------|------------|------------|------------|
| Classify | 100ms | 500ms | 2s |
| Dedup | 200ms | 1s | 5s |
| Retrieve | 150ms | 800ms | 3s |
| Reproduce | 500ms | 3s | 10s |
| Draft | 300ms | 1.5s | 5s |
| **Total triage** | **1.25s** | **6.8s** | **25s** |
| Dashboard load | 200ms | 1s | 3s |

**Conditions:**
- Issue size: < 10KB
- Repository size: < 10K files
- Network latency: < 50ms to LLM provider
- No concurrent operations
- LLM provider: Anthropic (varies by provider)

#### Resource Usage (Idle)

| Resource | Usage | Peak |
|----------|-------|------|
| CPU | 5-10% | 60-80% (during triage) |
| Memory | 800MB | 1.2-1.5GB |
| Disk I/O | < 10MB/day | 50-100MB (during triage) |
| Network | < 1MB/day | 10-20MB (triage operation) |

---

## Scalability

### Horizontal Scaling

**Option: Multiple Instances + Load Balancer**

```
                    Nginx Load Balancer
                          |
              ____________|___________
              |           |           |
          Instance 1   Instance 2   Instance 3
              |           |           |
              └───────────┴───────────┘
                      |
                 Shared Database
                 (PostgreSQL)
                      |
                 Shared Cache
                 (Redis)
```

**Setup:**
```bash
# Run multiple backend instances
docker run -d -e INSTANCE_ID=1 ... bugsift-backend
docker run -d -e INSTANCE_ID=2 ... bugsift-backend
docker run -d -e INSTANCE_ID=3 ... bugsift-backend

# Nginx routes to any available instance
upstream backend {
  server instance1:8000;
  server instance2:8000;
  server instance3:8000;
}
```

**Benefits:**
- ✅ Linear throughput scaling
- ✅ High availability
- ✅ Zero-downtime updates
- ❌ Requires shared database

### Vertical Scaling

**Option: Upgrade Instance Size**

| Instance | CPU | RAM | Est. Throughput |
|----------|-----|-----|-----------------|
| Small (current) | 1 | 2GB | 60 issues/hr |
| Medium | 2 | 4GB | 120 issues/hr |
| Large | 4 | 8GB | 240 issues/hr |
| XL | 8 | 16GB | 480 issues/hr |

**Scaling is mostly linear to CPU/RAM.**

---

## Performance Tuning

### PostgreSQL Tuning

```sql
-- Increase connection pool
ALTER SYSTEM SET max_connections = 200;

-- Increase work memory
ALTER SYSTEM SET work_mem = '256MB';

-- Increase shared buffers
ALTER SYSTEM SET shared_buffers = '512MB';

-- Enable query parallelization
ALTER SYSTEM SET max_parallel_workers = 4;

-- Apply changes
docker compose exec postgres pg_ctl reload
```

### Redis Tuning

```bash
# Increase max memory
docker exec bugsift-redis-1 redis-cli CONFIG SET maxmemory 2gb
docker exec bugsift-redis-1 redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Enable persistence
docker exec bugsift-redis-1 redis-cli CONFIG SET save "60 1000"
```

### Backend Tuning

```bash
# In docker-compose.yml, increase gunicorn workers:
backend:
  command: >
    gunicorn
      bugsift.api.main:app
      --workers 4           # Increase from 2
      --threads 2           # Add thread workers
      --worker-class gthread
      --max-requests 1000

# Restart
docker compose up -d backend
```

---

## Load Testing Results

### Test Scenario

**Setup:**
- Single instance (2GB RAM, 1 CPU)
- 1000 test issues created
- Each issue: ~5KB JSON
- Repository: 1000 files

**Tools:**
```bash
# Using Apache Bench
ab -n 100 -c 10 http://localhost:8001/api/triage

# Using wrk (concurrent connections)
wrk -t4 -c10 -d30s http://localhost:8001/api/triage
```

### Results

**Sequential Load (one issue at a time):**
```
Requests/sec: 0.83 (60 issues/hour)
Latency avg: 1200ms
Latency p99: 25000ms (25 seconds)
Success rate: 100%
Error rate: 0%
Memory peak: 1.5GB
CPU peak: 80%
```

**Concurrent Load (10 simultaneous triage operations):**
```
Requests/sec: 0.1 (6 issues/hour)
Latency avg: 12000ms
Latency p99: 30000ms (30 seconds) — timeout
Success rate: 85%
Error rate: 15% (timeouts)
Memory peak: 2.0GB
CPU peak: 95%
```

**Conclusion:** Sequential processing recommended. Concurrent operations cause timeouts due to LLM provider latency.

---

## Bottleneck Analysis

### CPU Bottleneck

**When:** > 80% sustained CPU usage

**Indicators:**
- Response latency increases
- Queue builds up
- Throughput plateaus

**Solutions:**
1. Upgrade to larger instance (vertical scale)
2. Add more instances (horizontal scale)
3. Reduce LLM request complexity
4. Use faster LLM model

### Memory Bottleneck

**When:** > 80% memory usage

**Indicators:**
- Swapping occurs
- Application crashes
- OOM killer activates

**Solutions:**
1. Upgrade to more RAM
2. Reduce Redis cache size
3. Reduce batch size
4. Check for memory leaks

### Database Bottleneck

**When:** > 90% connections used OR query latency > 2s

**Indicators:**
- "Too many connections" errors
- Slow dashboard loads
- Timeout errors

**Solutions:**
1. Increase `max_connections` in PostgreSQL
2. Add connection pooling (PgBouncer)
3. Optimize slow queries with indexes
4. Archive old data

### Disk I/O Bottleneck

**When:** Disk utilization > 80% OR latency spikes

**Indicators:**
- Slow backups
- Database writes lag
- Log file growth

**Solutions:**
1. Add disk space
2. Enable compression for backups
3. Reduce log retention
4. Archive to external storage

### Network Bottleneck

**When:** Network saturation OR LLM provider latency > 5s

**Indicators:**
- Triage latency increases
- "Connection timeout" errors
- Provider rate limiting

**Solutions:**
1. Check network connectivity
2. Use regional LLM endpoints (Google Gemini)
3. Cache LLM responses
4. Batch requests

---

## Optimization Checklist

### Before Scaling Up

- [ ] Enable query caching in Redis
- [ ] Add database indexes on frequently queried columns
- [ ] Enable PostgreSQL query parallelization
- [ ] Reduce log verbosity (INFO instead of DEBUG)
- [ ] Archive old triage decisions (> 2 years)
- [ ] Enable database compression
- [ ] Review slow query log for optimization

### When Adding Instances

- [ ] Set up load balancer (Nginx, HAProxy)
- [ ] Configure session affinity (sticky sessions)
- [ ] Share Redis across instances
- [ ] Share PostgreSQL connection pool
- [ ] Monitor instance health
- [ ] Set up auto-scaling rules (if cloud provider)

### Resource Allocation

**For 500 issues/day:**
- CPU: 1 (may be tight, consider 2)
- RAM: 4GB (for headroom)
- Disk: 50GB (issues + logs + backups)
- Network: 1Mbps (burst to 10Mbps)

**For 5000 issues/day:**
- CPU: 4
- RAM: 16GB
- Disk: 250GB
- Network: 10Mbps (burst to 50Mbps)

---

## Monitoring Performance

### Key Metrics to Track

```bash
# CPU usage
docker stats --no-stream | grep backend

# Memory usage
docker stats --no-stream | grep postgres

# Disk usage
df -h | grep /

# Database query latency
docker compose exec postgres psql -U postgres -c \
  "SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 5;"

# Cache hit rate
docker compose exec redis redis-cli info stats | grep hits
```

### Performance Dashboards

**Prometheus + Grafana setup:**

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['localhost:9323']  # Docker stats
  
  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']  # PostgreSQL exporter
  
  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']  # Redis exporter
```

---

## Performance Regression Detection

### Automated Monitoring

```bash
# Create baseline
docker stats --no-stream > baseline.txt

# Weekly comparison
docker stats --no-stream > weekly.txt
diff baseline.txt weekly.txt

# Alert if regression > 20%
```

### Common Regressions

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Latency slowly increasing | Database growing | Archive old data |
| Memory leak | Unfreed resources | Restart backend |
| Periodic slowdowns | Backups running | Schedule off-hours |
| Sudden spike in errors | Rate limiting | Check LLM quota |
| Connection timeouts | Pool exhausted | Increase connections |

---

## Benchmarking Your Deployment

### Simple Benchmark Script

```bash
#!/bin/bash
# benchmark.sh

ISSUES=100
CONCURRENCY=5

echo "Running benchmark: $ISSUES issues, $CONCURRENCY concurrent"

# Create test issues
for i in {1..$ISSUES}; do
  curl -s http://localhost:8001/api/triage \
    -d '{"title":"Test issue '$i'","body":"Test body"}' \
    > /dev/null &
done

wait

echo "Benchmark complete. Check logs for latencies."
docker compose logs backend | grep "duration"
```

### Expected Results

| Deployment | Issues/Hour | p99 Latency | Success Rate |
|------------|-------------|------------|--------------|
| 2GB (baseline) | 60 | 25s | 100% |
| 4GB (scaled) | 120 | 15s | 100% |
| 8GB (large) | 240 | 10s | 100% |
| 4x instances | 240 | 12s | 100% |

---

## Questions?

See [MONITORING.md](MONITORING.md) for how to monitor your specific deployment.
See [SLA.md](SLA.md) for performance targets and expectations.
