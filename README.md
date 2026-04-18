# bugsift

**Sift signal from noise in your issue tracker.**

bugsift is a maintainer's triage agent for open-source GitHub repositories.
It does not write fixes. It classifies, deduplicates, reproduces, and routes
incoming issues so a maintainer's attention goes only to the issues that
actually need it.

- **Who it's for:** solo / small-team OSS maintainers drowning in 50–500
  open issues on a single repo.
- **Who it's not for:** internal engineering teams (v2 territory) or anyone
  wanting an AI pair programmer (different product).

## What it does

When a new issue arrives, bugsift's deterministic pipeline runs within
~90 seconds and produces a **triage card** in the dashboard:

1. **Classify** — `bug`, `feature-request`, `question`, `docs`, `spam`, or
   `other` with a confidence score.
2. **Dedup** — cosine search over past issues plus an LLM judge, short-
   circuits when a true duplicate is found.
3. **Retrieve** — for bugs, points to the 3–5 most likely relevant files in
   the repo (with line ranges and GitHub deep links).
4. **Reproduce** — for bugs with concrete signal, drafts a minimal script
   and runs it in a hardened ephemeral Docker sandbox.
5. **Draft** — writes the triage comment, proposes labels, picks an action.

In **dry-run** the maintainer approves / edits / skips each card from the
dashboard. In **auto** mode, allow-listed actions (confirmed duplicates,
needs-info) execute without approval. Everything is per-repo configurable.

## Quick start (local)

Requires Docker 24+ and Docker Compose.

```bash
git clone https://github.com/joym-gits/bugsift.git
cd bugsift
./scripts/setup.sh           # copies .env.example → .env, fills secrets
docker compose up --build -d
docker compose exec backend alembic upgrade head
```

Open **http://localhost:8080**. Signed-out you'll see the dashboard shell.
To actually trigger triage:

1. Register a GitHub App following [docs/installation.md §4](docs/installation.md).
   Paste its credentials into `.env` and `docker compose up -d backend worker`
   to restart.
2. Click **Sign in with GitHub**, install the App on a repo, then add an
   Anthropic API key via **Settings**.
3. Open an issue on the installed repo. A triage card appears within ~90 s.

## Architecture at a glance

| Layer | Stack |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy 2.0 async · Redis + RQ |
| Database | Postgres 15 + pgvector |
| Frontend | Next.js 14 App Router · Tailwind · TanStack Query |
| LLM providers | Anthropic · OpenAI · Google · Ollama (user brings their own key) |
| Sandbox | Docker-in-Docker, read-only rootfs, caps dropped, 60 s hard timeout |
| E2E | Playwright |
| Deployment | single `docker-compose.yml`; self-hostable, no SaaS in v1 |

The design is deterministic — no LangChain, no LangGraph, no ReAct loops.
One small orchestrator in ~300 lines runs the pipeline steps in a fixed
order. See [docs/architecture.md](docs/architecture.md).

## Non-goals (v1)

- **No PR generation.** No code fixes. No commits.
- **GitHub only.** No GitLab / Bitbucket / Gitea.
- **No Slack / email / web intake.** Issues only.
- **No chat UI.** The agent acts; the maintainer ratifies.
- **No hosted SaaS.** Self-hostable `docker-compose` stack only.
- **No agent framework** dependency.

## Repo layout

- [backend/](backend/) — FastAPI, pipeline, workers, tests.
- [frontend/](frontend/) — Next.js 14 dashboard.
- [scripts/](scripts/) — setup helper, golden-set seed/eval.
- [docs/](docs/) — installation, configuration, architecture, self-hosting.
- [.github/workflows/ci.yml](.github/workflows/ci.yml) — lint + tests on PR.

## Running tests

```bash
# Backend: 121 unit + route tests
cd backend
.venv/bin/pytest -q -m "not live"

# Optional live-provider tests (need ANTHROPIC_API_KEY etc. in env)
.venv/bin/pytest -q -m live

# Frontend: vitest + Playwright smoke
cd ../frontend
npm test
npm run test:e2e        # requires docker compose up

# Golden-set classification eval (brief §16, target ≥ 85%)
ANTHROPIC_API_KEY=... backend/.venv/bin/python scripts/eval-goldenset.py
```

Current classification accuracy: **28/30 = 93.33%** on the hand-labelled
golden set (3 OSS repos, 30 closed issues).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
