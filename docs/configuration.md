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
