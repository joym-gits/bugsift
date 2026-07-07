# bugsift v0.2.0 — Role-Based Access Control (RBAC)

This document defines roles, permissions, and access control in bugsift.

---

## Role Overview

bugsift has four role levels:

| Role | Use Case | Permissions | Count |
|------|----------|-------------|-------|
| **Admin** | System administration | All operations | 1-2 |
| **Triager** | Daily issue triage | Approve/edit/skip, routing | 5-20 |
| **Reviewer** | Review & oversight | View, audit logs, reports | 2-5 |
| **Viewer** | Read-only access | View dashboards and data | unlimited |

---

## Permission Matrix

### Dashboard & UI

| Feature | Admin | Triager | Reviewer | Viewer |
|---------|-------|---------|----------|--------|
| View dashboard | ✅ | ✅ | ✅ | ✅ |
| View triage cards | ✅ | ✅ | ✅ | ✅ |
| View metrics/reports | ✅ | ✅ | ✅ | ✅ |
| Access audit logs | ✅ | ❌ | ✅ | ❌ |

### Issue Triage Operations

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Approve triage | ✅ | ✅ | ❌ | ❌ |
| Edit triage comment | ✅ | ✅ | ❌ | ❌ |
| Skip/dismiss card | ✅ | ✅ | ❌ | ❌ |
| Undo decision | ✅ | ✅ | ❌ | ❌ |
| View decision history | ✅ | ✅ | ✅ | ✅ |

### Repository & Configuration

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Add repository | ✅ | ❌ | ❌ | ❌ |
| Remove repository | ✅ | ❌ | ❌ | ❌ |
| Edit repo config | ✅ | ❌ | ❌ | ❌ |
| View repo settings | ✅ | ❌ | ✅ | ❌ |

### Routing Rules

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Create routing rule | ✅ | ❌ | ❌ | ❌ |
| Edit routing rule | ✅ | ❌ | ❌ | ❌ |
| Delete routing rule | ✅ | ❌ | ❌ | ❌ |
| View routing rules | ✅ | ✅ | ✅ | ❌ |

### LLM & API Keys

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Add LLM key | ✅ | ❌ | ❌ | ❌ |
| Rotate LLM key | ✅ | ❌ | ❌ | ❌ |
| View LLM budget | ✅ | ✅ | ✅ | ❌ |
| Create API token | ✅ | ❌ | ❌ | ❌ |
| Revoke API token | ✅ | ❌ | ❌ | ❌ |

### User Management

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Add user | ✅ | ❌ | ❌ | ❌ |
| Remove user | ✅ | ❌ | ❌ | ❌ |
| Change user role | ✅ | ❌ | ❌ | ❌ |
| View user list | ✅ | ✅ | ✅ | ❌ |
| Reset password | ✅ | ❌ | ❌ | ❌ |

### Logs & Audit

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| View audit log | ✅ | ❌ | ✅ | ❌ |
| Export audit log | ✅ | ❌ | ✅ | ❌ |
| View error logs | ✅ | ❌ | ✅ | ❌ |
| Clear logs | ✅ | ❌ | ❌ | ❌ |

### System & Deployment

| Operation | Admin | Triager | Reviewer | Viewer |
|-----------|-------|---------|----------|--------|
| Update settings | ✅ | ❌ | ❌ | ❌ |
| View system logs | ✅ | ❌ | ✅ | ❌ |
| Trigger backup | ✅ | ❌ | ❌ | ❌ |
| View deployment status | ✅ | ✅ | ✅ | ❌ |

---

## Role Descriptions

### Admin

**Purpose:** System administration and configuration.

**Responsibilities:**
- Manage users and roles
- Configure GitHub App integration
- Set up LLM keys and budgets
- Create routing rules
- Monitor system health
- Manage backups and updates
- Review audit logs

**Recommended for:**
- Deployment owner
- Operations team lead
- Security officer

**Best Practice:**
- Keep to 1-2 people
- Enable 2FA
- Rotate credentials every 90 days

---

### Triager

**Purpose:** Daily issue triage work.

**Responsibilities:**
- Review triage cards
- Approve/edit/skip decisions
- Monitor SLA compliance
- Track metrics

**Permissions:**
- ✅ Everything Viewer can do
- ✅ Approve triage decisions
- ✅ Edit comment drafts
- ✅ Create/manage feedback
- ❌ Configure system
- ❌ Manage users
- ❌ Access secrets

**Recommended for:**
- Maintenance team
- Support team
- Issue triagers

**Best Practice:**
- Session timeout: 12 hours
- API token rotation: 30 days
- Monitor: who approved what, when

---

### Reviewer

**Purpose:** Oversight and compliance.

**Responsibilities:**
- Review triage decisions
- Audit logs
- Quality assurance
- Compliance reporting

**Permissions:**
- ✅ View all dashboards
- ✅ Access audit logs
- ✅ Export reports
- ❌ Approve/edit triage
- ❌ Manage configuration
- ❌ Access secrets

**Recommended for:**
- QA team
- Compliance officer
- Management

**Best Practice:**
- Read-only access
- Session timeout: 24 hours
- Regular log reviews

---

### Viewer

**Purpose:** Information access only.

**Responsibilities:**
- View metrics and dashboards
- Monitor status
- Reference material

**Permissions:**
- ✅ View triage cards
- ✅ View dashboards
- ✅ View metrics
- ❌ Approve/edit
- ❌ Access logs
- ❌ Configure anything

**Recommended for:**
- Executive sponsors
- Product managers
- Stakeholders

**Best Practice:**
- No session timeout (passive)
- API tokens not supported
- Share-only dashboards

---

## Session & Token Management

### Sessions

| Parameter | Value |
|-----------|-------|
| Session duration | 12 hours (Triager/Reviewer) |
| Session duration | 24 hours (Admin) |
| Idle timeout | 1 hour (all roles) |
| Concurrent sessions | 1 per user |
| Remember login | 30 days (optional) |

### API Tokens

| Parameter | Value |
|-----------|-------|
| Token validity | 1 year |
| Rotation frequency | 30 days recommended |
| Max tokens per user | 3 |
| Auto-revoke unused | After 90 days |
| Scope | Per-token granularity |

**Creating an API token:**
```bash
# (In admin dashboard)
1. Go to Settings → API Tokens
2. Click "Create Token"
3. Select scope (read, write, admin)
4. Set expiration (1-365 days)
5. Copy token immediately (not shown again)
```

---

## Audit Trail

Every action by every user is logged:

| Field | Value |
|-------|-------|
| User | Who did it |
| Action | What did they do |
| Resource | What did they act on |
| Timestamp | When (UTC) |
| IP address | Where from |
| Result | Success/failure |
| Details | Any details (errors, old value, new value) |

**Actions logged:**
- Login/logout
- Role changes
- Triage decisions (approve/edit/skip)
- Configuration changes
- Secret management (create/rotate/delete keys)
- User additions/removals
- Backup triggers
- System updates

**Example audit entry:**
```
User: alice@company.com
Action: approve_triage
Resource: issue#1234 on repo/my-app
Timestamp: 2026-07-07T14:30:45Z
IP: 192.168.1.100
Result: success
Details: approved with comment edit, assigned to @bob
```

---

## Multi-Tenancy (Self-Hosted)

### Single Organization

Standard bugsift deployment = single organization.

- All users share the same database
- All users see all triage cards
- Roles determine what each user can do
- No data isolation between users

### Multi-Organization (Custom)

For completely isolated organizations:

**Option 1: Multiple Deployments**
- Separate `docker-compose` stack for each org
- Separate database, separate domain
- Highest isolation
- Highest cost

**Option 2: Database Schemas**
- One deployment, multiple PostgreSQL schemas
- One schema per org
- Requires custom configuration

**Option 3: Row-Level Security (RLS)**
- One database, row-level filtering
- Requires bugsift modification
- Best for many small orgs

---

## Default Users & Passwords

### First Installation

After installation, you'll set up:
1. **Bootstrap token** (shown once)
2. **First admin account** (email + password)

**Security notes:**
- Bootstrap token: single-use, expires after 24h
- First admin password: change immediately
- Add other admins via admin dashboard

### Default Roles

New users start as:
- **Invited by admin:** Role assigned by admin
- **Self-signup:** Default to Viewer (if enabled)

---

## RBAC Best Practices

### Principle of Least Privilege

> Give each user the minimum permissions they need to do their job.

- ✅ Triagers get Triager role (not Admin)
- ✅ Viewers get Viewer role (read-only)
- ✅ Rotate Admin access to 1-2 people
- ❌ Don't give everyone Admin access

### Principle of Separation of Duties

> Critical decisions need oversight.

- Admin configures LLM keys
- Triager uses them
- Reviewer audits decisions
- No single person controls everything

### Regular Access Reviews

**Monthly:**
- Who has access?
- Is it still needed?
- Any suspicious activity in audit log?

**Quarterly:**
- Rotate admin tokens
- Review user list
- Remove inactive users

### Incident Response

If a user's account is compromised:
1. Immediately revoke all tokens
2. Force logout all sessions
3. Review recent actions in audit log
4. Reset password
5. Notify other admins

---

## Troubleshooting

### "Permission Denied" Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Can't approve triage | Not Triager role | Ask admin to upgrade your role |
| Can't access logs | Not Admin/Reviewer | Only Admin/Reviewer can view audit logs |
| Can't add users | Not Admin | Only Admin can manage users |
| Token invalid | Expired/revoked | Create new token in dashboard |

### Locked Out (Admin)

If the only admin account is locked:

```bash
# Emergency: Use admin bootstrap token (if still valid)
# Or: Database direct access (advanced)

# Reset admin password via postgres
docker compose exec postgres psql -U postgres

# SELECT id FROM "User" WHERE email='admin@example.com';
# UPDATE "User" SET password_hash=NULL WHERE id='...';
# Then: Reset password via login page
```

### Session Timeout

Sessions expire after idle timeout (1 hour). To extend:
- Check "Remember me" on login
- Session extends to 30 days

---

## Compliance Notes

### GDPR Implications

- Users have right to access their data
- Users have right to delete their data
- Audit logs must be retained for compliance
- Admin must be able to export user actions

### SOC 2 Requirements

- ✅ Role-based access control
- ✅ Audit logging (append-only)
- ✅ Access reviews (quarterly recommended)
- ✅ Incident response procedures

---

## API Token Scopes (Advanced)

When creating API tokens, you can limit scope:

| Scope | Operations |
|-------|-----------|
| `triage:read` | View triage cards only |
| `triage:write` | Approve/edit/skip |
| `metrics:read` | View dashboards/reports |
| `config:read` | View configuration |
| `admin` | Full access |

**Example:**
```bash
# Create a read-only token for integrations
curl -X POST http://localhost:8001/api/tokens \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{
    "name": "external-integration",
    "scope": ["triage:read", "metrics:read"],
    "expires_in_days": 365
  }'
```

---

## Questions?

- **Role question:** See role descriptions above
- **Permission denied:** Check your role in Settings
- **Need to change roles:** Contact your Admin
- **Found a security issue:** See [SECURITY.md](SECURITY.md)

See [MONITORING.md](MONITORING.md) for auditing user actions.
