# Self-hosting

bugsift is designed to be self-hosted. No hosted SaaS is offered in v1.

## Recommended topology (localhost)

A single host running `docker-compose up` with the bundled stack:

- `postgres` (pgvector)
- `redis`
- `backend` (FastAPI)
- `worker` (RQ worker)
- `frontend` (Next.js)
- `nginx` reverse proxy on `:8080`

This is appropriate for personal use and for evaluating bugsift on small to
mid-size repos.

## Recommended topology (VPS, single host)

Same layout as localhost, behind your own TLS termination. Point a domain at
the VPS, terminate TLS at a reverse proxy in front of the bundled nginx, and
set `BUGSIFT_PUBLIC_URL=https://yourdomain`.

A 2 vCPU / 4 GB VPS is enough for one maintainer managing several repos of
moderate size.

## Secrets

All secrets are loaded from environment variables. `.env.example` documents
every required var. Never commit `.env`.

Sensitive vars:

- `BUGSIFT_ENCRYPTION_KEY` — losing this invalidates every stored API key.
  Back it up out-of-band.
- `GITHUB_APP_PRIVATE_KEY` (or `_PATH`) — issuing installation tokens.
- `GITHUB_APP_WEBHOOK_SECRET` — used to verify every incoming webhook.
- `POSTGRES_PASSWORD` — change from the default.

## Backups

- Postgres — standard `pg_dump`, at least daily.
- Redis — only holds transient queue state; does not need to be backed up.
- `.env` — back up separately from the repo (out-of-band).

## Upgrades

```bash
git pull
docker-compose build
docker-compose run --rm backend alembic upgrade head
docker-compose up -d
```

Always run `alembic upgrade head` before the updated containers come up.

## Observability (v1 minimum)

Every container logs to stdout. Pipe `docker-compose logs -f` to your log
aggregator of choice. No built-in Prometheus metrics in v1.

## Scaling

- **More repos / more issues per minute:** run more `worker` replicas. Redis
  handles the fan-out.
- **Large codebases (>50k files):** embedding costs dominate. Raise
  `monthly_budget_usd` or disable the retrieval step for that repo.
- **Reproduction throughput:** each reproduction holds a CPU and 512MB for up
  to 60 seconds. Bound the number of concurrent workers to your host's
  resources.
