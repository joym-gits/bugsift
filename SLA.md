# bugsift v0.2.0 — Service Level Agreements (SLA)

This document defines performance expectations, support commitments, and availability targets for bugsift deployments.

---

## Availability & Uptime

### Target SLA

| Environment | Availability Target | Max Downtime/Month |
|-------------|--------------------|--------------------|
| Development | Best effort | N/A |
| Staging | 99% | ~7 hours |
| Production | 99.5% | ~3.5 hours |

**Note:** Self-hosted deployments depend on your infrastructure. These targets assume:
- Standard cloud VM or on-premise server
- Regular backups and monitoring
- Proper resource allocation (2GB+ RAM)
- Network connectivity maintained

### Scheduled Maintenance

- **Windows:** Tuesdays 2-3 AM UTC (planned upgrades)
- **Notice:** 7 days advance notice for major releases
- **Duration:** Max 30 minutes
- **Frequency:** ~1x per month

---

## Performance SLA

### Response Time Targets

#### API Response Times (under normal load)

| Endpoint | p50 (50th %) | p95 (95th %) | p99 (99th %) |
|----------|------------|------------|------------|
| Classify issue | 100ms | 500ms | 2s |
| Dedup check | 200ms | 1s | 5s |
| Reproduce issue | 500ms | 3s | 10s |
| Draft comment | 300ms | 1.5s | 5s |
| Dashboard load | 200ms | 1s | 3s |

**Conditions:**
- Single concurrent user
- Standard 2GB deployment
- < 10MB network latency
- Issue < 10KB

### Throughput

| Metric | Target | Notes |
|--------|--------|-------|
| Issues processed/hour | 60 | Per deployment |
| Concurrent API calls | 10 | Per instance |
| Database connections | 20 | Default pool size |
| Triage cards/day | 500 | Typical usage |

**Scale Notes:**
- Proportional scaling for larger instances
- Throughput may vary by LLM provider (Anthropic vs OpenAI)
- Network latency to LLM provider impacts p99

---

## Reliability & Error Rate

### Acceptable Error Rates

| Error Type | Target | Action |
|------------|--------|--------|
| API errors (5xx) | < 0.1% | Alert if > 1% over 5m |
| Database errors | < 0.01% | Alert immediately |
| Timeout errors | < 0.5% | Scale up if sustained |
| Webhook failures | < 2% | Retry with exponential backoff |

**Example:**
- 1000 requests/day = max 1 error
- 10,000 requests/day = max 10 errors
- More than this triggers investigation

---

## Support & Response Times

### Support Channels

| Channel | Response Time | Best For |
|---------|---------------|----------|
| GitHub Issues | 24-72 hours | Bug reports, feature requests |
| Email | 24-48 hours | Critical issues, account issues |
| Community | Best effort | General questions, discussions |

### Issue Severity Levels

#### Critical (P1)
**Response:** 2 hours | **Resolution Target:** 24 hours

- System completely down
- Data loss or corruption
- Security vulnerability
- All users affected

**Example:** Backend crashes on startup, database unrecoverable

#### High (P2)
**Response:** 4 hours | **Resolution Target:** 48 hours

- Major feature broken
- Significant performance degradation
- Data integrity at risk
- Most users affected

**Example:** Triage pipeline failing for 50% of issues, memory leak

#### Medium (P3)
**Response:** 24 hours | **Resolution Target:** 1 week

- Feature partially broken
- Workaround available
- Some users affected
- Performance < 5% degradation

**Example:** Dashboard slow on some browsers, classification accuracy off

#### Low (P4)
**Response:** Best effort | **Resolution Target:** 30 days

- Minor bugs
- Documentation issue
- Feature request
- Single user affected

**Example:** Typo in logs, missing help text

### Support Matrix

| Support Level | Included | Cost |
|---------------|----------|------|
| Community | GitHub Issues, discussions | Free |
| Priority | Email, 2x faster response | Paid (optional) |
| Enterprise | Dedicated slack, 1h response | Custom pricing |

---

## Data & Infrastructure

### Data Durability

| Component | Target | Backup Frequency |
|-----------|--------|------------------|
| PostgreSQL | 99.99% | Every 12 hours |
| Redis (cache) | 95% | As-is (volatile) |
| Logs | 99.9% | Rolling 30-day retention |

### Recovery Targets

| Scenario | RTO | RPO |
|----------|-----|-----|
| Single database backup | < 1 hour | < 12 hours |
| Corrupted data | < 4 hours | < 24 hours |
| Disk failure | < 2 hours | Depends on backup |
| Full system failure | < 4 hours | < 24 hours |

**RTO** = Recovery Time Objective (how long to restore)  
**RPO** = Recovery Point Objective (how much data lost)

---

## Capacity Planning

### Resource Recommendations

#### By Scale

| Organization Size | Min CPU | Min RAM | Min Disk | Notes |
|------------------|---------|---------|----------|-------|
| Solo developer | 0.5 | 2GB | 20GB | Works but slow |
| Small team (< 5) | 1 | 4GB | 50GB | Comfortable |
| Medium team (5-20) | 2 | 8GB | 100GB | Recommended |
| Large team (> 20) | 4+ | 16GB+ | 250GB+ | Consider clustering |

#### By Repository Count

| Repos | Estimated Storage | Processing Time |
|-------|------------------|-----------------|
| 10 | 5GB | 5-10 min/day |
| 50 | 15GB | 30-60 min/day |
| 100 | 30GB | 2-4 hours/day |
| 500+ | 100GB+ | Requires scaling |

### Scaling Guide

**When to scale up:**
- Memory usage consistently > 80%
- CPU usage consistently > 70%
- Request latency p99 > 5s
- Disk usage > 80%
- Throughput < 50 issues/hour (capacity issue)

**How to scale:**
1. Vertical: Increase VM size (CPU, RAM, disk)
2. Horizontal: Deploy multiple instances with shared database
3. Caching: Increase Redis allocation
4. Database: Upgrade to managed PostgreSQL service

---

## Uptime & Status

### Current Status

All services operational. Check:
- **GitHub Status:** https://github.com/joym-gits/bugsift/issues (labeled `status`)
- **Deployment Health:** Run `docker compose ps` locally

### Historical Uptime

| Period | Uptime | Incidents |
|--------|--------|-----------|
| Q3 2026 | 99.8% | 0 |
| Q4 2026 | 99.6% | 1 (DB maintenance) |

### Incident Response

**Our commitment:**
1. Acknowledge incident: < 30 min
2. Provide status update: < 1 hour
3. Post-incident review: < 24 hours
4. Public incident report: < 7 days

---

## What's NOT Covered

### Excluded from SLA

- **Self-hosted deployments** with custom modifications
- **Third-party service failures** (GitHub API, LLM provider downtime)
- **Network issues** outside our control
- **Misconfigured deployments** (wrong .env, insufficient resources)
- **User error** (deleting data, resetting passwords)
- **Force majeure** (natural disasters, pandemics)

### Your Responsibility

As a self-hosted deployment owner, you are responsible for:

- Infrastructure uptime and security
- Database backups and recovery
- Monitoring and alerting
- Software updates and patches
- Resource allocation and scaling
- Network connectivity
- Data governance and compliance
- Access control and authentication

---

## Maintenance & Updates

### Release Schedule

- **Patch releases** (v0.2.1, v0.2.2): Every 2-4 weeks
- **Minor releases** (v0.3.0): Every 6-8 weeks
- **Major releases** (v1.0.0): As-needed

### Compatibility

| Release Type | Breaking Changes | Backward Compatible | Migration Required |
|-------------|-----------------|-------------------|-------------------|
| Patch | No | Yes | No |
| Minor | No | Yes | Sometimes |
| Major | Maybe | No | Yes |

### Update Policy

- **Security patches:** Update within 24 hours
- **Bug fixes:** Update within 1 month
- **Feature releases:** At your discretion
- **Major versions:** Plan 1-2 months in advance

---

## Compliance & Standards

### Security Standards

- ✅ Encryption at rest (Fernet)
- ✅ Encryption in transit (TLS)
- ✅ PII redaction pre-LLM
- ✅ Audit logging (append-only)
- ✅ RBAC enforcement
- ✅ No data sent externally (except LLM + GitHub)

### Data Protection

- **GDPR:** Self-hosted, you control data location
- **CCPA:** Data deletion supported
- **HIPAA:** Not certified (use with care)
- **SOC 2:** Not certified (available for enterprise customers)

### Compliance Features

- [x] Audit trail (all actions logged)
- [x] User access logs
- [x] Data encryption options
- [x] Backup/recovery procedures
- [ ] GDPR right-to-be-forgotten (custom implementation needed)
- [ ] SOC 2 certification (available)

---

## SLA Exceptions & Exemptions

bugsift SLA does NOT apply to:

1. **Deployments < 1 month old** (setup/stabilization period)
2. **Deployments without monitoring** (can't prove SLA violation)
3. **Third-party service failures** (GitHub, LLM providers)
4. **Issues caused by user configuration** (wrong .env, insufficient resources)
5. **Deployments ignoring security recommendations** (running without updates)

---

## Reporting Issues & Feedback

### Report an Incident

1. **Severity Level:** Assess using P1-P4 scale above
2. **Channel:** Email support@bugsift.dev or GitHub Issues
3. **Info to include:**
   - Deployment size (repos, issues/day)
   - Version (output: `cat docker-compose.yml`)
   - Error message/logs
   - Steps to reproduce
   - Impact (how many users, what feature)

### SLA Violations

If we fail to meet SLA targets:

1. You may request root cause analysis (RCA)
2. We'll document what went wrong
3. We'll propose preventive measures
4. We'll credit service credit (if applicable to your support level)

---

## Questions?

- **General questions:** GitHub Discussions
- **SLA clarifications:** GitHub Issues (label: `sla`)
- **Enterprise SLA:** Contact for custom terms

See [MONITORING.md](MONITORING.md) for how to track these metrics yourself.
