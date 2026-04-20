<a name="top"></a>

<p align="center">
  <a href="https://github.com/joym-gits/bugsift">
    <img src="./assets/banner.svg" alt="bugsift — sift signal from noise in your issue tracker" width="100%"/>
  </a>
</p>

<p align="center">
  <strong>⭐ Star us on GitHub — your support motivates us a lot! 🙏😊</strong>
</p>

<p align="center">
  <a href="https://github.com/joym-gits/bugsift/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/joym-gits/bugsift?color=ea7a1c&label=release&style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/releases/latest"><img alt="Release date" src="https://img.shields.io/github/release-date/joym-gits/bugsift?color=ea7a1c&style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/joym-gits/bugsift/ci.yml?branch=main&label=CI&style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/actions/workflows/publish-images.yml"><img alt="Images" src="https://img.shields.io/github/actions/workflow/status/joym-gits/bugsift/publish-images.yml?branch=main&label=images&style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/joym-gits/bugsift?color=blue&style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/joym-gits/bugsift?style=flat-square"/></a>
  <a href="https://github.com/joym-gits/bugsift/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/joym-gits/bugsift?color=ea7a1c&style=flat-square"/></a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11-3776ab?logo=python&logoColor=white&style=flat-square"/>
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white&style=flat-square"/>
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white&style=flat-square"/>
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-15%20%2B%20pgvector-4169e1?logo=postgresql&logoColor=white&style=flat-square"/>
  <img alt="Redis" src="https://img.shields.io/badge/Redis-7-dc382d?logo=redis&logoColor=white&style=flat-square"/>
  <img alt="Docker" src="https://img.shields.io/badge/Docker-self--hosted-2496ed?logo=docker&logoColor=white&style=flat-square"/>
  <img alt="Anthropic" src="https://img.shields.io/badge/LLM-Anthropic%20%2F%20OpenAI%20%2F%20Google%20%2F%20Ollama-0a0a0a?style=flat-square"/>
</p>

<p align="center">
  <a href="https://twitter.com/intent/tweet?text=bugsift%20%E2%80%94%20self-hosted%20GitHub%20issue%20triage%20that%20learns%20from%20your%20team.%20One-command%20install%2C%20no%20SaaS.&url=https%3A%2F%2Fgithub.com%2Fjoym-gits%2Fbugsift"><img alt="Share on Twitter" src="https://img.shields.io/badge/-Share%20on%20X-000000?logo=x&logoColor=white&style=flat-square"/></a>
  <a href="https://news.ycombinator.com/submitlink?u=https%3A%2F%2Fgithub.com%2Fjoym-gits%2Fbugsift&t=bugsift%20%E2%80%94%20self-hosted%20GitHub%20issue%20triage"><img alt="Share on Hacker News" src="https://img.shields.io/badge/-Share%20on%20HN-ff6600?logo=ycombinator&logoColor=white&style=flat-square"/></a>
  <a href="https://www.reddit.com/submit?url=https%3A%2F%2Fgithub.com%2Fjoym-gits%2Fbugsift&title=bugsift%20%E2%80%94%20self-hosted%20GitHub%20issue%20triage"><img alt="Share on Reddit" src="https://img.shields.io/badge/-Share%20on%20Reddit-ff4500?logo=reddit&logoColor=white&style=flat-square"/></a>
  <a href="https://www.linkedin.com/sharing/share-offsite/?url=https%3A%2F%2Fgithub.com%2Fjoym-gits%2Fbugsift"><img alt="Share on LinkedIn" src="https://img.shields.io/badge/-Share%20on%20LinkedIn-0a66c2?logo=linkedin&logoColor=white&style=flat-square"/></a>
</p>

<p align="center">
  🔥 <strong>Why bugsift?</strong> Because at 100 open issues on a solo repo, reading each one is the work. bugsift classifies, dedups, reproduces, and drafts a reply in ~90 seconds — you only see what needs you.
</p>

---

## 🚀 About

**bugsift** is a maintainer's triage agent for GitHub repositories. It
does *not* write fixes. It **classifies**, **deduplicates**,
**reproduces**, and **routes** incoming issues so a maintainer's
attention goes only to the issues that actually need it.

- **Who it's for:** solo and small-team maintainers drowning in
  50–500 open issues on a single repo, and product teams running an
  in-app feedback widget that funnels user reports into the same
  triage flow.
- **Who it's not for:** teams wanting an AI pair programmer (different
  product), or anyone who wants a hosted SaaS — bugsift runs on *your*
  infrastructure, on purpose.
- **The one-liner:** *AI triage without the AI tax.* You bring the
  LLM key, bugsift brings the orchestration, the sandbox, the
  operator UI, and everything around the model.

> [!IMPORTANT]
> bugsift is **self-hosted by design**. Your GitHub tokens, issue
> bodies, and operator decisions never leave a box you control. The
> installer puts the full stack on any Docker host in five minutes.

## ⚡ Quick start

```sh
# One command. No cloning. No hand-editing .env. No manual migrations.
curl -fsSL https://github.com/joym-gits/bugsift/releases/latest/download/install.sh | bash

# Installer generates secrets, pulls pre-built images from GHCR,
# runs migrations, and prints your dashboard URL + bootstrap token.

# Open the dashboard:
open http://localhost:8080

# Pin a specific release for reproducibility:
BUGSIFT_IMAGE_TAG=v0.1.0 \
  curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.1.0/install.sh | bash
```

Full walkthrough including upgrades, backups, and Caddy-backed TLS:
📋 [Self-host guide](deploy/README.md).

## ✨ What's new

See 📋 [Release notes](https://github.com/joym-gits/bugsift/releases)
for every version. Highlights from recent drops:

- 🧠 **Feedback-loop learning** — every approve / skip / edit
  becomes retrieval context so triage compounds with your team's
  decisions.
- ⚖️ **Routing rules + SLA tracking** — operator-defined rules
  match classification / severity / repo and accumulate actions
  (assign, label, notify Slack, set SLA). Breach alerts fire on a
  60 s Redis-locked watcher.
- 🏛️ **Enterprise surface** — RBAC (admin / triager / viewer),
  append-only audit log with CSV export, PII + credential redaction
  before every LLM call, and a metrics dashboard.
- 🛡️ **Production security pass** — install-callback CSRF via App-
  API verification, sandbox `network_mode=none`, Docker socket
  proxied and read-only, SSRF guard on outbound URLs, bootstrap
  token on first-run registration, nonce-based CSP via Next.js
  middleware.
- 🎨 **UI/UX uplift** — warm-orange brand, Inter, tile grid + side
  sheet dashboard.

## 🧩 Features

- **Classify** — `bug`, `feature-request`, `question`, `docs`, `spam`,
  or `other` with a confidence score. Recent operator corrections feed
  back into the prompt so the classifier learns your team's voice.
- **Dedup** — cosine search over past-issue embeddings plus an LLM
  judge. Short-circuits when a true duplicate is found and drafts a
  "duplicates #123" comment automatically.
- **Retrieve** — points at the 3–5 most likely relevant files in the
  repo with line ranges and GitHub deep links. Refined post-repro by
  the traceback's file paths when reproduction succeeded.
- **Reproduce** — drafts a minimal repro script and runs it in a
  hardened ephemeral Docker sandbox: `network_mode=none`,
  `--read-only`, `--cap-drop=ALL`, 60 s hard timeout. No network
  egress, no privileged containers.
- **Draft** — writes the triage comment, proposes labels, picks a
  proposed action. Human approves / edits / skips.
- **CODEOWNERS-driven assign** — suggested assignees derive from the
  last-match CODEOWNERS rule; operator selects which to actually
  assign via checkbox.
- **Routing rules** — *"if severity=blocker on `my-org/api-*`, assign
  @sec-team, add label `critical`, notify #incidents, SLA 60 min."*
- **SLA tracking** — breach alerts via Slack; compliance % on the
  metrics dashboard.
- **Jira + GitHub destinations** — approve routes to either (or both)
  per feedback-app configuration.
- **Slack notifications** — new-card / approved / regression /
  sla-breach events, per-destination filters, rule-targeted
  overrides.
- **Audit log** — every security-relevant action (login, role change,
  approve, key rotation, App register/delete) recorded, append-only,
  CSV-exportable.
- **RBAC** — admin / triager / viewer roles; last-admin can't demote
  themselves.
- **PII redaction** — emails, phones, SSN, Luhn-valid cards, provider
  API keys (Anthropic/OpenAI/Google/AWS/Slack/GitHub), JWTs, URL
  credentials — scrubbed before any prompt touches the LLM, stable
  `[redacted:kind:hash8]` tokens preserve referential integrity.
- **Feedback widget** — drop-in JS snippet for end-user bug reports;
  rate-limited ingest, CORS-gated per app, dedup against existing
  cards.
- **Metrics dashboard** — throughput, LLM cost by provider / model /
  step, approval rate, PII scrub rate, SLA compliance — all in one
  admin page.

## 🛡️ Security

> [!NOTE]
> bugsift runs in production under a hardened posture out of the
> box. Every listed item below is *on* by default — you opt out, not
> in.

- **Every secret encrypted at rest** via Fernet (GitHub App PEM, OAuth
  secret, webhook secret, user LLM keys, Slack webhook URLs, Jira API
  tokens). The master key never ships in logs or API responses.
- **Sandbox isolation** — reproduction containers have
  `network_mode=none`, read-only root, tmpfs scratch, no Linux caps,
  strict memory + pids + CPU caps, 60 s wall-clock kill.
- **Docker socket never mounted on application containers** — the
  worker talks to Docker through `tecnativa/docker-socket-proxy`
  scoped to containers + images with POST/DELETE only.
- **CSP with per-request nonces** via Next.js middleware —
  `strict-dynamic` script-src that accepts no inline scripts other
  than the nonced ones Next.js emits itself.
- **GitHub install-callback ownership verification** — refuses to
  re-parent an installation to a different user; verifies installation
  account against the authenticated GitHub login.
- **SSRF-safe outbound HTTP** — every user-supplied URL (e.g. Jira
  site) resolves + checks against private/loopback/link-local/CGNAT
  ranges before the first request.
- **Bootstrap token** gates first-run GitHub App registration in
  production so a drive-by visitor to a pre-onboarding deployment
  can't claim it.
- **Rate-limited feedback ingest** with trusted-proxy-aware per-IP
  and global per-app counters.
- **PII + credential redaction** before every LLM call — details
  above under [Features](#-features).

> [!IMPORTANT]
> Found a vulnerability? Please read [SECURITY.md](SECURITY.md) for
> coordinated disclosure — don't open a public issue.

## 🏗️ Architecture

| Layer | Stack |
|---|---|
| **Backend** | Python 3.11 · FastAPI · SQLAlchemy 2.0 async · Redis + RQ |
| **Database** | Postgres 15 + pgvector |
| **Frontend** | Next.js 14 App Router · Tailwind · TanStack Query · Inter |
| **LLM providers** | Anthropic · OpenAI · Google · Ollama (user brings their own key) |
| **Sandbox** | Docker-in-Docker via socket proxy · read-only rootfs · caps dropped · 60 s kill |
| **E2E tests** | Playwright |
| **Deployment** | single `docker-compose.yml` · multi-arch images on GHCR · self-hostable |

The design is **deterministic** — no LangChain, no LangGraph, no
ReAct loops. One small orchestrator in ~300 lines runs the pipeline
steps in a fixed order. See
[docs/architecture.md](docs/architecture.md).

## 🧱 Self-host guide

- 📋 [Install + upgrade + backup](deploy/README.md)
- 📋 [Caddy + Let's Encrypt TLS](deploy/docker-compose.caddy.yml)
- 📋 [GitHub App registration](docs/installation.md)
- 📋 [Configuration reference](docs/configuration.md)

## 🧪 Running from source (contributors)

```bash
git clone https://github.com/joym-gits/bugsift.git
cd bugsift
./scripts/setup.sh               # copies .env.example → .env, fills secrets
docker compose up --build -d
docker compose exec backend alembic upgrade head

# Backend tests (121 unit + route tests)
cd backend && .venv/bin/pytest -q -m "not live"

# Optional live-provider tests (needs ANTHROPIC_API_KEY etc.)
.venv/bin/pytest -q -m live

# Frontend tests (vitest + Playwright smoke)
cd ../frontend && npm test && npm run test:e2e

# Golden-set classification eval (brief §16, target ≥ 85%)
ANTHROPIC_API_KEY=... backend/.venv/bin/python scripts/eval-goldenset.py
```

Current classification accuracy: **28/30 = 93.33%** on the
hand-labelled golden set (3 OSS repos, 30 closed issues).

## 🧭 Non-goals (v1)

- **No PR generation.** No code fixes. No commits.
- **GitHub only.** No GitLab / Bitbucket / Gitea (yet).
- **No chat UI.** The agent acts; the maintainer ratifies.
- **No hosted SaaS.** Self-hostable `docker-compose` stack only.
- **No agent framework dependency.**

## 🤝 Contributing

Pull requests, issues, and ideas welcome. Good first places to
contribute:

- Improve the classification golden set (labels + edge cases).
- Add a new ticket destination (Linear, ServiceNow, …).
- Add a match condition or action to the routing-rules engine.
- Improve the reproduction sandbox's language coverage.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## 📃 License

[Apache 2.0](LICENSE) — free to self-host, fork, and modify for any
purpose, commercial or otherwise.

## 🗨️ Contact

- **Issues + feature requests:** [github.com/joym-gits/bugsift/issues](https://github.com/joym-gits/bugsift/issues)
- **Security reports:** [SECURITY.md](SECURITY.md)
- **Discussions:** [github.com/joym-gits/bugsift/discussions](https://github.com/joym-gits/bugsift/discussions)

---

<p align="center">
  <sub>Built with warm orange · by maintainers, for maintainers · <a href="#top">back to top ↑</a></sub>
</p>
