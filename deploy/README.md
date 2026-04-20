# Self-hosting bugsift

bugsift is designed to run on your own infrastructure — your GitHub
tokens and issue bodies never leave a box you control. The stack is
Docker-Compose-based and fits comfortably on a single 2 GB VM.

## Quick start

**Requirements:** Docker 24+, the `compose` plugin, and ~2 GB RAM.

```sh
curl -fsSL https://github.com/joym-gits/bugsift/releases/latest/download/install.sh | bash
```

The installer lands a `bugsift/` directory in your working folder,
generates every secret, pulls images from GitHub Container Registry,
runs migrations, and prints the dashboard URL + a first-run
**bootstrap token**.

Open `http://localhost:8080`, click **Register GitHub App**, paste
the token when prompted, and follow the wizard. Total time from
`curl` to your first triaged issue: under five minutes.

> Prefer to read before running anything? Download the script first:
> `curl -fsSLo install.sh https://github.com/joym-gits/bugsift/releases/latest/download/install.sh`, then `less install.sh`.

### Pin a version

The default command always fetches the latest release. To pin both
the installer and the running container images to a specific version:

```sh
BUGSIFT_IMAGE_TAG=v0.1.0 \
  curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.1.0/install.sh | bash
```

Every [release](https://github.com/joym-gits/bugsift/releases)
publishes `install.sh`, `docker-compose.prod.yml`,
`docker-compose.caddy.yml`, and a `bugsift-deploy.tar.gz` bundle.

## What's in the box

| Container      | Image                                         | Purpose                                     |
| -------------- | --------------------------------------------- | ------------------------------------------- |
| `postgres`     | `pgvector/pgvector:pg15`                      | Cards, embeddings, feedback reports, audit. |
| `redis`        | `redis:7-alpine`                              | RQ job queue + rate-limit counters.         |
| `backend`      | `ghcr.io/<owner>/bugsift-backend:latest`      | FastAPI.                                    |
| `worker`       | same image as backend                         | RQ worker: triage + reproduction sandbox.   |
| `docker-proxy` | `tecnativa/docker-socket-proxy:0.3`           | Scoped Docker API for the sandbox.          |
| `frontend`     | `ghcr.io/<owner>/bugsift-frontend:latest`     | Next.js dashboard.                          |
| `nginx`        | `nginx:1.27-alpine`                           | Reverse proxy on :8080.                     |

The reproduction sandbox spawns per-card containers through
`docker-proxy` with `network_mode="none"`, `--read-only`,
`--cap-drop=ALL`, and a 60 s timeout. The worker itself never sees
`/var/run/docker.sock`.

## Day-to-day operations

```sh
cd bugsift
docker compose logs -f backend       # tail backend logs
docker compose ps                    # service health
docker compose pull && docker compose up -d   # upgrade to latest images
docker compose down                  # stop (data persists in volumes)
```

### Upgrade

```sh
docker compose pull
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

Migrations are backward-compatible within a minor version. Skim
`CHANGELOG.md` on major releases for any operator-action items.

### Backup

Everything worth saving lives in two volumes: `bugsift_postgres_data`
and `bugsift_redis_data`. A nightly `pg_dump` is enough for most
self-hosters:

```sh
docker compose exec -T postgres pg_dump -U bugsift bugsift \
  | gzip > "backup-$(date +%F).sql.gz"
```

Restore onto a fresh deployment:

```sh
gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose exec -T postgres \
  psql -U bugsift bugsift
```

Back up `.env` alongside the dump — it holds the Fernet key without
which every encrypted row (API keys, App PEM, Slack webhooks) is
unrecoverable.

## Putting TLS in front

The default nginx listens on plain HTTP 8080 so you can put whatever
reverse proxy you already run (Caddy, Traefik, Cloudflare Tunnel,
nginx-proxy, ALB, …) in front. The repo ships a ready-made Caddy
override:

```sh
# Add to .env:
#   BUGSIFT_DOMAIN=bugs.example.com
#   BUGSIFT_ACME_EMAIL=ops@example.com
#   BUGSIFT_PUBLIC_URL=https://bugs.example.com
#   NEXT_PUBLIC_API_BASE_URL=https://bugs.example.com/api

curl -fsSLo docker-compose.caddy.yml \
  https://raw.githubusercontent.com/joym-gits/bugsift/main/deploy/docker-compose.caddy.yml

docker compose \
  -f docker-compose.yml \
  -f docker-compose.caddy.yml up -d
```

Caddy provisions Let's Encrypt certificates on first boot and renews
them automatically.

## Configuration reference

Everything is in `.env`. Only the values you'd actually change:

| Variable                     | Default                | Notes                                                                     |
| ---------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| `BUGSIFT_PUBLIC_URL`         | `http://localhost:8080`| The URL users reach the dashboard at. Update when you put TLS in front.   |
| `BUGSIFT_PUBLIC_PORT`        | `8080`                 | Host port the nginx binds to.                                             |
| `BUGSIFT_ENV`                | `production`           | `development` skips hardening (no HTTPS cookie, no bootstrap token gate). |
| `BUGSIFT_BOOTSTRAP_TOKEN`    | *(generated)*          | Required on the first-run GitHub App registration in production.         |
| `BUGSIFT_IMAGE_TAG`          | `latest`               | Pin a specific release: `v0.4.1`. See the [Releases tab].                 |
| `BUGSIFT_TRUST_PROXY`        | `1`                    | Read `X-Real-IP` for rate-limit keying. Set `0` if no proxy is in front.  |

[Releases tab]: https://github.com/joym-gits/bugsift/releases

Secrets regenerated by re-running the installer only if you first
delete the existing `.env` — otherwise the file is left untouched.

## Troubleshooting

**`bad gateway` right after signing in.** The OAuth callback redirected
you to `BUGSIFT_PUBLIC_URL`; if that's `localhost:8080` but you're
browsing from elsewhere, set it to the real external URL and restart.

**`BUGSIFT_ENCRYPTION_KEY is not a valid Fernet key` at boot.** The
installer uses `openssl rand -base64 32` which macOS' LibreSSL
sometimes returns with padding that Fernet rejects. Regenerate:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and put it in `.env`.

**The sandbox can't start containers.** Make sure `docker-proxy` is
running (`docker compose ps`). The worker talks to Docker over TCP
through that proxy; a missing or misconfigured proxy breaks
reproduction without affecting classification.

**Feedback widget rate limits hit too often.** The per-IP cap is
intentionally tight; change `INGEST_RATE_LIMIT_PER_MIN` in the
backend container env if you're hosting a high-traffic widget.

## What bugsift does **not** do for you

- **User management across organizations.** Each deployment is a
  tenant. RBAC (admin / triager / viewer) lives inside the
  deployment, but one deployment maps to one GitHub org's triage
  flow.
- **Hosted storage.** No cards, issue bodies, or feedback reports
  leave your Postgres. You own every byte.
- **Automated upgrades.** `docker compose pull` is manual on purpose —
  you decide when to take new migrations.

## Licence + issues

Source is Apache 2.0; see the repository root. Issues and feature
requests at [github.com/joym-gits/bugsift](https://github.com/joym-gits/bugsift/issues).
