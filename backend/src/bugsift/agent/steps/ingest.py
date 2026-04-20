"""Step 1 — Ingest.

Translate a GitHub ``issues.opened`` webhook payload plus the stored repo
row into a :class:`TriageState`. No LLM calls here; just assembly.
"""

from __future__ import annotations

from typing import Any

from bugsift.agent.state import TriageState
from bugsift.pii.redact import redact


def from_webhook_payload(
    *,
    payload: dict[str, Any],
    repo_id: int,
    repo_full_name: str,
    repo_primary_language: str | None,
    repo_config: dict[str, Any],
) -> TriageState:
    issue = payload.get("issue") or {}
    # Scrub PII + credentials before the body ever touches the LLM.
    # The raw payload is still stored on the triage card (``raw_payload``)
    # so the dashboard can show operators the original; the LLM only ever
    # sees the redacted versions.
    title_redacted = redact(str(issue.get("title") or ""))
    body_redacted = redact(str(issue.get("body") or ""))
    merged_counts: dict[str, int] = {}
    for k, v in title_redacted.counts.items():
        merged_counts[k] = merged_counts.get(k, 0) + v
    for k, v in body_redacted.counts.items():
        merged_counts[k] = merged_counts.get(k, 0) + v
    return TriageState(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        repo_primary_language=repo_primary_language,
        issue_number=int(issue.get("number") or 0),
        issue_title=title_redacted.text,
        issue_body=body_redacted.text,
        pii_redacted=merged_counts,
        issue_author=str((issue.get("user") or {}).get("login", "")),
        existing_labels=[
            str(lbl.get("name", "")) for lbl in (issue.get("labels") or []) if lbl.get("name")
        ],
        raw_payload=payload,
        tone=str(repo_config.get("tone") or "professional"),
        label_map=dict(repo_config.get("label_map") or {}),
        auto_actions=dict(repo_config.get("auto_actions") or {}),
        mode=repo_config.get("mode") or "dry-run",
        enabled_steps=dict(repo_config.get("enabled_steps") or {}),
    )
