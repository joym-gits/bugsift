# Configuration

Per-repo configuration lives in the `repo_configs` table and is editable from
the dashboard's **Settings** page. The defaults below are applied at install
time.

## Defaults

```yaml
mode: dry-run                # dry-run | auto
monthly_budget_usd: 10
tone: professional           # professional | friendly | terse
enabled_steps:
  classify: true
  dedup: true
  retrieval: true
  reproduction: true
auto_actions:                # which actions may execute without approval
  duplicate: true
  needs_info: true
  bug: false
  feature_request: false
label_map:
  bug: "bug"
  needs_info: "needs-info"
  duplicate: "duplicate"
  good_first_issue: "good-first-issue"
  feature_request: "enhancement"
reproduce_languages: [python, node]
```

## Field reference

- **mode** — `dry-run` queues every card for approval; `auto` posts cards
  whose `proposed_action` is in the `auto_actions` allowlist.
- **monthly_budget_usd** — hard cap in USD across all LLM calls for this repo
  in the current calendar month. Never exceeded by more than 10%.
- **tone** — drafting tone used by the comment step.
- **enabled_steps** — any step can be switched off. Classification is always
  on; the others can be turned off to save tokens or skip expensive work.
- **auto_actions** — per-action allowlist for auto-mode. `bug` defaults to
  `false` because real bugs should always see a human.
- **label_map** — maps bugsift's internal label slugs to the label names that
  actually exist on your repo. Missing labels are skipped.
- **reproduce_languages** — which primary languages trigger the reproduction
  step. Python and Node are the v1 supported set.

## Editing

Changes take effect on the next issue event. To backfill decisions already
made under the old config, delete the affected triage cards and re-process
the issues manually via `scripts/index-repo.py`.

## Embedding provider

Dedup (Step 3) and codebase retrieval (Step 4) both use vector embeddings.
Anthropic has no embeddings API, so if you've only configured an Anthropic
key the pipeline will cleanly skip dedup/retrieval and still run classify +
comment. To unlock dedup and retrieval you need one additional key.

Preference order (first available wins):

| Provider | Model | Dimension | Cost |
|---|---|---|---|
| OpenAI | `text-embedding-3-small` | 1536 | ~$0.02 / 1M tokens |
| Ollama | `nomic-embed-text` | 768 | free, local |
| Google | `text-embedding-004` | 768 | free tier |

Each repo pins to whichever model's embeddings it first stored. Switching
providers requires a full re-index:

```bash
backend/.venv/bin/python scripts/index-repo.py --repo owner/name
```

Per-repo dimension and model are visible in `repos.embedding_model` /
`repos.embedding_dim`.
