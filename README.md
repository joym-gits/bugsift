# bugsift

**Sift signal from noise in your issue tracker.**

bugsift is a maintainer's triage agent for open-source GitHub repositories. It
does not write fixes. It classifies, deduplicates, reproduces, and routes
incoming issues so that a maintainer's attention goes only to the issues that
actually need it.

## Status

Early development. Currently in **Phase 1** (scaffolding). The system does not
yet do anything interesting — you can bring up the stack and hit `/health`, but
the triage pipeline is not implemented.

See the [project brief](./docs/architecture.md) for the canonical specification,
non-goals, and build plan.

## Quick start (local)

Requires Docker and Docker Compose.

```bash
git clone https://github.com/joym-gits/bugsift.git
cd bugsift
cp .env.example .env
# Edit .env and fill in the required variables (see comments in the file)
docker-compose up --build
```

Then visit:

- Frontend: http://localhost:8080
- Backend health check: http://localhost:8080/api/health

## Layout

- [backend/](backend/) — FastAPI service, triage pipeline, workers.
- [frontend/](frontend/) — Next.js 14 dashboard.
- [docs/](docs/) — installation, configuration, architecture, self-hosting.
- [docker-compose.yml](docker-compose.yml) — production-style local stack.
- [docker-compose.dev.yml](docker-compose.dev.yml) — dev overlay with hot reload.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
