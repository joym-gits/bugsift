# Contributing to bugsift

Thanks for your interest in contributing. bugsift is in early development and
we are keeping the surface area small. The fastest way to help right now is to
file issues that flag bugs or missing pieces in the scoped v1 work; please do
not open PRs that expand scope beyond the current phase without discussion.

## Ground rules

1. **Read the project brief first.** It is the canonical spec and locks
   architectural decisions. Proposals that re-litigate the stack, the non-goals,
   or the phase order need to open an issue first and get a maintainer ack
   before code lands.
2. **Stay in scope.** Each phase of the build plan is a checkpoint. Don't ship
   work from phase N+2 while we're still stabilising phase N.
3. **No secrets in commits.** Every LLM key, GitHub App private key, or webhook
   secret loads from env vars. If you add a new secret, document it in
   `.env.example` and `docs/self-hosting.md`.

## Development setup

```bash
git clone https://github.com/joym-gits/bugsift.git
cd bugsift
cp .env.example .env
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Backend tests:

```bash
cd backend
pip install -e '.[dev]'
pytest
```

Frontend tests and typecheck:

```bash
cd frontend
npm install
npm run test
npm run typecheck
```

## Commit style

- Imperative subject line, under 72 characters (`add dedup short-circuit`).
- Reference the phase if it is phase-aligned (`phase 5: draft comment endpoint`).
- One logical change per commit when feasible.

## Reporting security issues

Do **not** file security issues in the public tracker. See [SECURITY.md](SECURITY.md).

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). By participating in this project
you agree to abide by its terms.
