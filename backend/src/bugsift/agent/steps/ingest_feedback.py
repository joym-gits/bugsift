"""Build a :class:`TriageState` from a widget-submitted feedback report.

Feedback reports are free-form text plus context (URL, user agent,
console log). We flatten that into the same ``issue_title`` +
``issue_body`` shape the rest of the pipeline already understands, so
classify / dedup / retrieval / reproduction all work without special
cases downstream.

Title synthesis is deliberately a heuristic (first meaningful line,
trimmed) rather than a fresh LLM call — running an extra generation
per report would triple cost for a piece of information the classifier
already produces implicitly. If the classifier wants a better title it
can surface one in ``rationale`` / ``draft_comment``.
"""

from __future__ import annotations

import re
from typing import Any

from bugsift.agent.state import TriageState
from bugsift.db.models import FeedbackReport

_WHITESPACE = re.compile(r"\s+")
_MAX_TITLE_LEN = 90


def from_feedback_report(
    *,
    report: FeedbackReport,
    repo_id: int,
    repo_full_name: str,
    repo_primary_language: str | None,
    repo_config: dict[str, Any],
) -> TriageState:
    title = _synthesize_title(report.body_text)
    body = _assemble_body(report)
    return TriageState(
        repo_id=repo_id,
        repo_full_name=repo_full_name,
        repo_primary_language=repo_primary_language,
        # 0 = "no GitHub issue yet"; the card writer maps this to NULL
        # and persists the feedback_report_ids instead.
        issue_number=0,
        issue_title=title,
        issue_body=body,
        issue_author="",  # end-user is anonymised by reporter_hash
        existing_labels=[],
        raw_payload={"feedback_report_id": report.id},
        tone=str(repo_config.get("tone") or "professional"),
        label_map=dict(repo_config.get("label_map") or {}),
        auto_actions=dict(repo_config.get("auto_actions") or {}),
        mode=repo_config.get("mode") or "dry-run",
        enabled_steps=dict(repo_config.get("enabled_steps") or {}),
    )


def _synthesize_title(body_text: str) -> str:
    """Pick the first non-empty line, collapse whitespace, clip to 90 chars.

    Good enough for the classifier and the UI, and cheap — no LLM call."""
    for raw_line in body_text.splitlines():
        line = _WHITESPACE.sub(" ", raw_line).strip()
        if not line:
            continue
        if len(line) <= _MAX_TITLE_LEN:
            return line
        # Cut at the last word boundary before the limit so we don't
        # end mid-word.
        clipped = line[: _MAX_TITLE_LEN]
        space = clipped.rfind(" ")
        if space > 40:
            clipped = clipped[:space]
        return clipped.rstrip(",. ") + "\u2026"
    return "User feedback"


def _assemble_body(report: FeedbackReport) -> str:
    """Append structured context after the user's own text so retrieval
    can pull stack traces + URLs from the same block the classifier reads.

    Intentionally plain text (not markdown) — Anthropic's classifier
    handles either, and the stack-trace regex is format-agnostic.
    """
    parts: list[str] = [report.body_text.strip()]

    appendix: list[str] = []
    if report.url:
        appendix.append(f"URL: {report.url}")
    if report.app_version:
        appendix.append(f"App version: {report.app_version}")
    if report.user_agent:
        appendix.append(f"User agent: {report.user_agent}")
    if report.console_log:
        # Trim so we don't blow past the classifier's cheap tier; the
        # retrieval step cares about the last frames far more than the
        # first.
        log = report.console_log.strip()
        if len(log) > 4000:
            log = log[-4000:]
        appendix.append(f"Console log:\n{log}")
    meta = report.client_meta_json or {}
    if isinstance(meta, dict) and meta:
        meta_lines = [f"{k}: {v}" for k, v in meta.items() if v is not None]
        if meta_lines:
            appendix.append("Client context: " + ", ".join(meta_lines))

    if appendix:
        parts.append("\n---\n" + "\n\n".join(appendix))

    return "\n".join(parts)
