# bugsift v0.2.0 — Compliance & Data Governance

This document covers compliance requirements, data protection, and regulatory obligations.

---

## Data Protection Regulations

### GDPR (Europe)

**Applicable to:** EU residents' data in bugsift

**bugsift compliance:**
- ✅ Data encryption at rest (Fernet)
- ✅ Data encryption in transit (TLS)
- ✅ Audit logs (record of access)
- ✅ Purpose limitation (triage only)
- ✅ Data minimization (PII redacted)
- ⚠️ Right to access (can export data)
- ⚠️ Right to deletion (manual process)
- ⚠️ Data residency (you control)

**Your responsibilities:**
- Privacy policy mentioning bugsift
- Consent for data processing (if needed)
- Vendor agreement with bugsift (Apache 2.0)
- Regular data access reviews
- Incident notification (72 hours)

**Data you control:**
- User email addresses
- GitHub tokens
- Triage decisions
- LLM provider keys
- Routing rules

---

### CCPA (California)

**Applicable to:** California residents

**bugsift compliance:**
- ✅ Transparency (this document)
- ✅ Right to know (export data)
- ✅ Right to delete (supported)
- ✅ Non-discrimination (no penalties)
- ❌ Not a "sale" (no data sold)
- ❌ No "sensitive data" flags (user-controlled)

**User rights in bugsift:**
- Right to access their data
- Right to delete their profile
- Right to opt-out of LLM processing

---

### HIPAA (Healthcare - US)

**Status:** NOT HIPAA compliant

**If you have healthcare data:**
- Do NOT use bugsift with protected health information (PHI)
- Do NOT use with HIPAA-regulated organizations
- Do NOT store patient data
- Do NOT use with healthcare GitHub repos containing PHI

**If needed:** Contact for custom HIPAA-compliant deployment

---

### SOC 2

**Status:** Self-hosted (you are responsible)

**Type I elements (controls):**
- ✅ Security: Encryption, sandbox isolation
- ✅ Availability: Health checks, monitoring
- ✅ Processing integrity: Data validation
- ✅ Confidentiality: PII redaction, RBAC
- ✅ Privacy: Audit logs, data residency

**Your obligations:**
- Implement access controls
- Monitor and audit usage
- Keep deployment updated
- Regular backups and testing
- Incident response procedures

---

## Data Classification

### Sensitive Data in bugsift

| Data | Classification | Protection |
|------|----------------|-----------|
| GitHub tokens | Secret | Fernet encryption, never logged |
| LLM API keys | Secret | Fernet encryption, never logged |
| Webhook secrets | Secret | Fernet encryption, never logged |
| User passwords | Secret | Bcrypt/Argon2 hashing |
| Audit logs | Confidential | Append-only, encrypted at rest |
| Issue bodies | Sensitive | PII redacted before LLM |
| User emails | Sensitive | In clear text (access controlled) |
| Triage decisions | Internal | Logged, audit trail |

### PII Redaction

**Before any LLM call, these are redacted:**

| Pattern | Redaction | Reason |
|---------|-----------|--------|
| Email addresses | `[EMAIL_1]`, `[EMAIL_2]` | Privacy |
| Phone numbers | `[PHONE_1]` | Privacy |
| SSN/ID numbers | `[SSN_1]` | Privacy |
| Credit card numbers | `[CARD_1]` | PCI DSS |
| API keys/tokens | `[TOKEN_1]` | Security |
| JWT tokens | `[JWT_1]` | Security |
| AWS/GCP/Azure credentials | `[CRED_1]` | Security |
| URLs with credentials | `[URL_CRED]` | Security |

**Example redaction:**
```
Before: "Contact alice@example.com for help"
After:  "Contact [EMAIL_1] for help"
```

Tokens are stable (same sensitive value → same token each time).

---

## Security Standards

### Encryption

#### At Rest

```yaml
Database secrets:
  GitHub tokens: Fernet encrypted
  API keys: Fernet encrypted
  Webhook secrets: Fernet encrypted
  User passwords: Bcrypt hashed (not encrypted)

Master key:
  Storage: .env ENCRYPTION_KEY (you control)
  Rotation: Manual (requires re-encryption)
  Backup: Included in database backups
```

#### In Transit

```yaml
HTTPS/TLS:
  Protocol: TLS 1.2 minimum
  Certificates: Let's Encrypt (via Caddy)
  HSTS: Enabled (force HTTPS)
  Cipher suites: Modern (no weak ciphers)

Internal:
  Docker network: Isolated bridge
  Redis: No auth (network-isolated)
  Database: Password authenticated
```

### Access Control

| Component | Control |
|-----------|---------|
| Dashboard | RBAC (Admin/Triager/Reviewer/Viewer) |
| API | API tokens with optional scopes |
| Database | PostgreSQL roles + network isolation |
| Redis | Network isolation only (trusted network) |
| Docker | Limited to deployment owner |

---

## Audit & Compliance

### Audit Trail

**What's logged:**

Every action:
- User (who)
- Action (what)
- Resource (on what)
- Timestamp (when, UTC)
- IP address (from where)
- Result (success/failure)

**Example entries:**

```
User: alice@company.com
Action: login
Timestamp: 2026-07-07T10:00:00Z
Result: success
IP: 192.168.1.100

User: bob@company.com
Action: approve_triage
Resource: issue#1234
Timestamp: 2026-07-07T10:05:30Z
Result: success
Details: comment edited

User: admin@company.com
Action: rotate_llm_key
Timestamp: 2026-07-07T14:00:00Z
Result: success
Old fingerprint: sha256:abc123...
```

### Audit Log Retention

| Log Type | Retention | Format |
|----------|-----------|--------|
| User actions | 1 year | JSON |
| System events | 1 year | JSON |
| Error logs | 90 days | Text |
| Access logs | 1 year | JSON |

**Export audit logs:**

```bash
# Via dashboard: Settings → Audit Logs → Export CSV
# Via API:
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8001/api/audit/logs?start=2026-01-01&end=2026-12-31 \
  > audit_logs.json
```

---

## Data Residency & Sovereignty

### Where Your Data Lives

**In Your Control:**
- ✅ PostgreSQL database (your server/cloud)
- ✅ Redis cache (your server/cloud)
- ✅ GitHub tokens (encrypted in your DB)
- ✅ Triage decisions (your server)
- ✅ Audit logs (your server)

**Sent Elsewhere (You Control):**
- GitHub API (GitHub.com)
- LLM provider (Anthropic/OpenAI/Google/Ollama)
- Webhook forwarding (if configured)

**Nothing Sent Without Your Action:**
- No telemetry to bugsift
- No phone-home checks
- No analytics
- No crash reporting
- You control all outbound data

---

## Breach Notification & Incident Response

### If Your Deployment is Breached

**Your responsibilities:**

1. **Discover:** Detect via monitoring/audit logs
2. **Contain:** Isolate affected systems (revoke tokens, rotate keys)
3. **Investigate:** Review audit logs, check for unauthorized access
4. **Notify:** Comply with local regulations (72 hours for GDPR)
5. **Remediate:** Patch, update, restore from backup

**How to investigate:**

```bash
# Check audit logs for suspicious activity
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM audit_log WHERE timestamp > '2026-07-07T10:00:00Z' ORDER BY timestamp DESC;"

# Check failed login attempts
docker compose logs backend | grep -i "failed login\|unauthorized"

# Verify token fingerprints
docker compose exec postgres psql -U postgres -c \
  "SELECT user_id, token_hash, created_at FROM api_token ORDER BY created_at DESC LIMIT 20;"

# Verify GitHub token access
curl -H "Authorization: token $(grep GITHUB_TOKEN .env)" \
  https://api.github.com/user/repos | jq '.[] | {name, pushed_at}'
```

### Template Breach Notification

```
Dear [User/Regulator],

We are notifying you of a security incident affecting your bugsift deployment.

Incident Details:
- Date discovered: [YYYY-MM-DD]
- Date of incident: [YYYY-MM-DD]
- Impact: [What data affected]
- Affected systems: [Which repos/users]

Actions Taken:
- [What was done to contain]
- [What was done to remediate]
- [What was done to prevent recurrence]

Your Data:
- Backup available: [YES/NO - restore point: YYYY-MM-DD HH:MM:SS]
- Recovery time: [Estimated X hours]

Next Steps:
- [What user should do]
- [Who to contact]

Sincerely,
[Your Name]
```

---

## Compliance Certifications

### Current Status

| Certification | Status | Notes |
|-------------|--------|-------|
| SOC 2 Type I | Available | Custom engagement required |
| SOC 2 Type II | Available | 6-month assessment required |
| ISO 27001 | Not certified | Available for enterprise |
| HIPAA | Not compliant | Healthcare data not supported |
| GDPR | Compliant | Data residency in your control |
| CCPA | Compliant | Data deletion supported |

### Getting Certified

**For SOC 2:**
1. Contact for audit engagement
2. Deploy with recommended security settings
3. 6-12 month assessment period
4. Receive SOC 2 report

**For HIPAA:**
1. Not supported (would require re-architecture)
2. Consider separate HIPAA-compliant deployment

---

## Compliance Checklists

### Pre-Deployment Checklist

- [ ] Legal: Reviewed with legal team
- [ ] Privacy: Privacy policy updated
- [ ] Data: Classified sensitive data
- [ ] Encryption: TLS enabled
- [ ] Access: RBAC configured
- [ ] Backup: Backup procedure tested
- [ ] Monitoring: Audit logging enabled
- [ ] Incident: Response plan documented

### Regular Compliance Reviews (Quarterly)

- [ ] Access review: Remove unused users
- [ ] Audit log review: Check for anomalies
- [ ] Backup test: Restore from backup
- [ ] Token rotation: Rotate API tokens
- [ ] Security: Check for updates
- [ ] Compliance: Verify SLA compliance

### Incident Response Checklist

- [ ] Contain: Stop data loss
- [ ] Investigate: Review audit logs
- [ ] Notify: Inform affected parties
- [ ] Remediate: Fix root cause
- [ ] Follow-up: Prevent recurrence
- [ ] Document: Log incident and response

---

## Third-Party Compliance

### GitHub

bugsift connects to GitHub API:
- ✅ GitHub has SOC 2 certification
- ✅ Tokens are read-only (limited scope)
- ✅ Tokens stored encrypted
- ❌ GitHub sees your issue content (by design)
- ❌ bugsift doesn't sign GitHub DPA

**Your responsibility:**
- Only use with public/approved repos
- Review GitHub's privacy policy
- Ensure GitHub App permissions match your policy

### LLM Providers

bugsift sends issue content to LLM:

**Anthropic Claude:**
- ✅ SOC 2 certified
- ✅ No data retention
- ✅ PII redacted before sending
- ⚠️ Data sent over HTTPS to US servers

**OpenAI:**
- ✅ SOC 2 certified
- ⚠️ May use data for training (check their policy)
- ⚠️ Data sent to US servers

**Google Gemini:**
- ✅ SOC 2 certified
- ✅ Can use regional endpoints
- ✅ GDPR-compliant

**Ollama (Self-hosted):**
- ✅ No data sent externally
- ✅ No training concerns
- ⚠️ You manage model updates

**Your responsibility:**
- Choose provider matching your policy
- Review their privacy agreements
- Redact sensitive data yourself if needed
- Inform users about LLM processing

---

## Data Deletion & Right to Be Forgotten

### How to Delete User Data

**For GDPR compliance:**

```bash
# Export all user data first (backup)
docker compose exec postgres pg_dump -U postgres bugsift > backup_before_delete.sql

# Delete user and all associated data:
docker compose exec postgres psql -U postgres << EOF
-- Get user ID
SELECT id FROM "User" WHERE email = 'user@example.com';

-- Delete triage cards (cascades)
DELETE FROM triage_card WHERE user_id = '<ID>';

-- Delete user
DELETE FROM "User" WHERE id = '<ID>';
EOF

# Verify deletion
docker compose exec postgres psql -U postgres -c \
  "SELECT * FROM \"User\" WHERE email = 'user@example.com';"
# Should return no rows
```

### Data Retention Policy

**Recommendation:**

| Data Type | Retention | Action |
|-----------|-----------|--------|
| User account (active) | Indefinite | Keep |
| User account (inactive 1yr) | 1 year | Delete on request |
| Triage decisions | 2 years | Auto-delete |
| Audit logs | 1 year | Archive then delete |
| Backups | 30 days | Auto-delete |
| Error logs | 90 days | Auto-delete |

---

## Questions?

- **Compliance question:** See appropriate section above
- **Need certification?:** Contact for engagement
- **Data deletion request?:** Contact admin
- **Security issue?:** See [SECURITY.md](SECURITY.md)

See [SLA.md](SLA.md) for support response times.
