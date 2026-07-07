# bugsift v0.2.0 — API Documentation

This document covers the bugsift REST API for programmatic access and integrations.

---

## Authentication

### API Tokens

Create tokens in Settings → API Tokens:

```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" \
  http://your-domain:8001/api/v1/triage-cards
```

### Token Scopes

| Scope | Permissions |
|-------|-----------|
| `triage:read` | Read triage cards, metrics |
| `triage:write` | Approve/edit/skip decisions |
| `config:read` | Read configuration |
| `admin` | Full access |

---

## API Endpoints

### Triage Cards

**List triage cards:**
```bash
GET /api/v1/triage-cards
Authorization: Bearer $TOKEN

Response:
{
  "cards": [
    {
      "id": "card-123",
      "issue_number": 456,
      "title": "Fix: connection pool leak",
      "status": "pending",
      "classification": "bug",
      "confidence": 0.95,
      "suggested_labels": ["bug", "database"],
      "suggested_assignee": "@alice",
      "created_at": "2026-07-07T10:00:00Z"
    }
  ],
  "pagination": {
    "offset": 0,
    "limit": 50,
    "total": 150
  }
}
```

**Get single card:**
```bash
GET /api/v1/triage-cards/{card_id}
```

**Approve card:**
```bash
POST /api/v1/triage-cards/{card_id}/approve
Content-Type: application/json

{
  "comment": "Approved. Assigned to @bob for fixing."
}
```

**Edit card:**
```bash
PATCH /api/v1/triage-cards/{card_id}

{
  "classification": "feature-request",
  "suggested_labels": ["enhancement", "feature"],
  "comment": "Actually this is a feature request, not a bug."
}
```

**Skip card:**
```bash
POST /api/v1/triage-cards/{card_id}/skip

{
  "reason": "Duplicate of #123"
}
```

### Repositories

**List repositories:**
```bash
GET /api/v1/repositories

Response:
{
  "repos": [
    {
      "id": "repo-123",
      "name": "api",
      "owner": "my-org",
      "installed": true,
      "issue_count": 42
    }
  ]
}
```

**Get repository config:**
```bash
GET /api/v1/repositories/{repo_id}/config

Response:
{
  "enabled": true,
  "auto_approve_confidence": 0.95,
  "skip_drafts": false,
  "routing_rules": []
}
```

### Metrics

**Get metrics:**
```bash
GET /api/v1/metrics?start=2026-07-01&end=2026-07-31

Response:
{
  "total_triaged": 150,
  "approved": 120,
  "skipped": 20,
  "accuracy": 0.89,
  "avg_latency_ms": 4200,
  "llm_spend": 12.34
}
```

### Audit Logs

**Get audit logs:**
```bash
GET /api/v1/audit-logs?start=2026-07-01&end=2026-07-31

Response:
{
  "logs": [
    {
      "timestamp": "2026-07-07T10:00:00Z",
      "user": "alice@company.com",
      "action": "approve_triage",
      "resource": "card-123",
      "result": "success"
    }
  ]
}
```

---

## Webhooks

### Custom Webhooks

Receive events when triage cards are updated:

```bash
# Register webhook in Settings → Integrations
POST /webhooks/triage

# Receives:
{
  "event": "triage.approved",
  "card": {
    "id": "card-123",
    "issue_number": 456,
    "title": "Fix: connection pool",
    "classification": "bug"
  },
  "timestamp": "2026-07-07T10:00:00Z"
}
```

### Webhook Events

- `triage.pending` — New card created
- `triage.approved` — Card approved
- `triage.skipped` — Card skipped
- `triage.edited` — Card edited

---

## Rate Limiting

**Limits:**
- 100 requests per minute per token
- 1000 requests per hour per token

**Headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1657180860
```

**When exceeded:**
```
429 Too Many Requests
Retry-After: 60
```

---

## Error Responses

**Format:**
```json
{
  "error": "unauthorized",
  "message": "Invalid API token",
  "status": 401
}
```

**Common errors:**
- `400 Bad Request` — Invalid input
- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient permissions
- `404 Not Found` — Resource not found
- `429 Too Many Requests` — Rate limited
- `500 Internal Server Error` — Server error

---

## SDK Examples

### Python

```python
import requests

token = "your_api_token"
headers = {"Authorization": f"Bearer {token}"}

# List cards
response = requests.get(
  "http://localhost:8001/api/v1/triage-cards",
  headers=headers
)
cards = response.json()["cards"]

# Approve card
requests.post(
  f"http://localhost:8001/api/v1/triage-cards/{cards[0]['id']}/approve",
  json={"comment": "Approved by automation"},
  headers=headers
)
```

### JavaScript

```javascript
const token = "your_api_token";
const headers = { "Authorization": `Bearer ${token}` };

// List cards
const response = await fetch(
  "http://localhost:8001/api/v1/triage-cards",
  { headers }
);
const cards = await response.json();

// Approve card
await fetch(
  `http://localhost:8001/api/v1/triage-cards/${cards[0].id}/approve`,
  {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ comment: "Approved" })
  }
);
```

### cURL

```bash
token="your_api_token"
domain="http://localhost:8001"

# List cards
curl -H "Authorization: Bearer $token" \
  "$domain/api/v1/triage-cards"

# Approve card
curl -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d '{"comment":"Approved"}' \
  "$domain/api/v1/triage-cards/card-123/approve"
```

---

## Integration Examples

### Slack Integration

Send approved cards to Slack:

```python
import requests
from slack_sdk import WebClient

bugsift_token = "bugsift_api_token"
slack_token = "slack_token"

bugsift_api = "http://localhost:8001/api/v1"
slack = WebClient(token=slack_token)

# Get approved cards from past hour
response = requests.get(
  f"{bugsift_api}/audit-logs?action=approve_triage&hours=1",
  headers={"Authorization": f"Bearer {bugsift_token}"}
)

for log in response.json()["logs"]:
  card = log["card"]
  slack.chat_postMessage(
    channel="#triage",
    text=f"✅ Approved: {card['title']} ({card['issue_number']})"
  )
```

### Jira Integration

Create Jira tickets from bugsift cards:

```python
from jira import JIRA
import requests

bugsift_token = "bugsift_api_token"
jira = JIRA("https://jira.company.com", basic_auth=("user", "password"))

response = requests.get(
  "http://localhost:8001/api/v1/triage-cards?status=approved",
  headers={"Authorization": f"Bearer {bugsift_token}"}
)

for card in response.json()["cards"]:
  jira.create_issue(
    project="BUG",
    issuetype="Bug",
    summary=card["title"],
    description=f"From bugsift: {card['id']}"
  )
```

---

## Versioning

**Current version:** `v1`

**Future versions:** Backward compatible with v1

**Deprecation policy:**
- 6 months notice before deprecating endpoints
- Parallel support for old + new versions

---

## Support

- **Issues:** https://github.com/joym-gits/bugsift/issues
- **Discussions:** https://github.com/joym-gits/bugsift/discussions
- **OpenAPI/Swagger:** `/api/docs` (in your deployment)

See [SLA.md](SLA.md) for response time expectations.
