# Installation

Stage 1 (Phase 1, current): you can bring up the stack but there is no triage
pipeline yet. The GitHub App section below is authoritative for Phase 3+ and
can be skipped for now.

## 1. Prerequisites

- Docker 24+ and Docker Compose.
- A GitHub account that owns (or has admin access to) the repo you want to
  triage.
- An Anthropic API key (for Phase 4+). Other providers are supported but
  Anthropic is the primary target during v1 development.
- At least 4GB of RAM free for the stack — Postgres, Redis, two backend
  processes, and Next.js all run in containers.

## 2. Clone and configure

```bash
git clone https://github.com/joym-gits/bugsift.git
cd bugsift
cp .env.example .env
```

Open `.env` and fill in at minimum:

- `BUGSIFT_ENCRYPTION_KEY` — generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `BUGSIFT_SESSION_SECRET` — any long random string, e.g.
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `POSTGRES_PASSWORD` — change from the default before exposing to anything
  beyond localhost.

GitHub App variables can stay blank until you finish step 4.

## 3. Bring up the stack

```bash
docker-compose up --build -d
# Apply database migrations on first boot (and after any pull):
docker-compose exec backend alembic upgrade head
```

Visit <http://localhost:8080> — you should see the dashboard. The backend
health check is at <http://localhost:8080/api/health>.

The "Sign in with GitHub" button is live from Phase 2 onwards, but the OAuth
flow only works once you complete §4 below and set `GITHUB_APP_CLIENT_ID` /
`GITHUB_APP_CLIENT_SECRET` in your `.env`. Until then the Start endpoint
returns 503 with an explanatory message.

For development with hot reload:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## 4. Register a GitHub App (Phase 3+)

bugsift ships as a **GitHub App**, not an OAuth application. Each maintainer
registers their own App on their account and points it at their bugsift
deployment. This keeps secrets local.

### 4.1 Create the App

1. Go to <https://github.com/settings/apps> and click **New GitHub App**.
2. **GitHub App name:** anything unique, e.g. `bugsift-<yourhandle>`.
3. **Homepage URL:** `http://localhost:8080` for local testing; your public
   URL otherwise.
4. **Callback URL:** `http://localhost:8080/api/auth/github/callback`.
5. **Webhook URL:** `http://localhost:8080/api/webhooks/github`. For a local
   install you will need to expose this publicly (see §4.4).
6. **Webhook secret:** generate a random 48-byte token and paste it in; save
   the same value to `.env` as `GITHUB_APP_WEBHOOK_SECRET`.
7. **Permissions — Repository:**
   - Contents: **Read-only** (for indexing)
   - Issues: **Read & write** (to post comments and apply labels)
   - Metadata: **Read-only** (default)
   - Pull requests: **Read-only**
8. **Permissions — Account:** leave all as **No access**.
9. **Subscribe to events:**
   - Issues
   - Issue comment
   - Push (to keep the index fresh on default-branch updates)
10. **Where can this GitHub App be installed?** Only on this account.

Save the App. You will be redirected to its settings page.

### 4.2 Collect credentials

From the App settings page, copy these into `.env`:

- **App ID** → `GITHUB_APP_ID`
- **Client ID** → `GITHUB_APP_CLIENT_ID`
- Click **Generate a new client secret**, copy once, save to
  `GITHUB_APP_CLIENT_SECRET`.
- Under **Private keys**, click **Generate a private key**. Save the resulting
  `.pem` file somewhere safe and either:
  - Set `GITHUB_APP_PRIVATE_KEY_PATH` to the container path where you mount
    the file, or
  - Paste the entire PEM into `GITHUB_APP_PRIVATE_KEY` (with `\n` between
    lines, one line total).

### 4.3 Install the App on a repo

1. From the App's public page click **Install App**.
2. Pick the repo(s) you want bugsift to triage.
3. After install, the dashboard at <http://localhost:8080/dashboard> will show
   the newly-installed repos.

### 4.4 Exposing the webhook publicly

GitHub needs to reach your webhook URL. For local installs use a tunnel:

```bash
# Option A: smee.io (zero-setup, reliable)
npx smee --url https://smee.io/<your-channel> --target http://localhost:8080/api/webhooks/github

# Option B: Cloudflare Tunnel or ngrok
cloudflared tunnel --url http://localhost:8080
```

Whichever option you pick, update the App's webhook URL to match.

## 5. Verify

From the dashboard:

1. Open **Settings**, add an Anthropic API key, and click **Test key**.
2. Open an issue on your installed repo with a clear title and body.
3. Within ~90 seconds the dashboard should show a new triage card.
4. Approve, edit, or skip the card.

If a card does not appear, check `docker-compose logs backend worker` and the
App's **Advanced → Recent Deliveries** page on GitHub.
