"""Slack Incoming Webhook notifier.

Two concerns:

1. **Event gating** — :data:`EVENTS` is the canonical set of event names
   the settings UI exposes. A destination's ``events_json`` is a flag
   set; an event fires only if the destination opted in.

2. **Message shape** — :func:`build_card_blocks` renders a card into
   Slack's Block Kit. One header block, one context block with the
   classification + confidence pill, a section with the rationale /
   first report body, optional sections for suspected files and
   regression suspects, and a final action row with a deep-link back
   into bugsift.

Delivery is a simple POST to the stored webhook URL. Errors are logged
and swallowed — a broken destination never breaks triage. Retries are
the responsibility of the caller (RQ job retry wrapper).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from bugsift.db.models import SlackDestination, TriageCard
from bugsift.security import crypto

logger = logging.getLogger(__name__)

# Canonical event names. The UI shows each as a checkbox; triage
# code dispatches with these strings.
EVENT_NEW_CARD = "new_card"
EVENT_APPROVED = "approved"
EVENT_REGRESSION = "regression"

EVENTS: tuple[str, ...] = (EVENT_NEW_CARD, EVENT_APPROVED, EVENT_REGRESSION)

# New destinations default to these events — the signal-to-noise ratio
# here is good (a new card you haven't looked at + real cause found).
DEFAULT_EVENTS: dict[str, bool] = {
    EVENT_NEW_CARD: True,
    EVENT_APPROVED: False,
    EVENT_REGRESSION: True,
}


@dataclass(frozen=True)
class SlackDeliveryResult:
    ok: bool
    status_code: int | None
    detail: str | None


def should_notify(destination: SlackDestination, event: str) -> bool:
    """Return ``True`` if ``destination`` opted in to ``event``.

    A destination with an empty / missing flag set acts like "notify on
    everything in :data:`DEFAULT_EVENTS`" so a brand-new destination
    isn't silent."""
    events = destination.events_json if isinstance(destination.events_json, dict) else None
    if not events:
        return bool(DEFAULT_EVENTS.get(event, False))
    return bool(events.get(event, False))


async def post_card_event(
    destination: SlackDestination,
    *,
    card: TriageCard,
    event: str,
    card_url: str,
    repo_full_name: str,
    lead_report_text: str | None = None,
) -> SlackDeliveryResult:
    """Send a Block Kit message for ``event`` on ``card`` to the
    destination's webhook URL. Swallows network errors into the return
    value; never raises."""
    try:
        webhook_url = crypto.decrypt(destination.webhook_url_encrypted)
    except crypto.DecryptionFailed:
        logger.warning("slack: decrypt failed for destination id=%s", destination.id)
        return SlackDeliveryResult(ok=False, status_code=None, detail="decrypt failed")

    blocks = build_card_blocks(
        card=card,
        event=event,
        card_url=card_url,
        repo_full_name=repo_full_name,
        lead_report_text=lead_report_text,
    )
    payload = {
        "text": _fallback_text(card=card, event=event, repo_full_name=repo_full_name),
        "blocks": blocks,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
    except httpx.HTTPError as e:
        logger.warning(
            "slack: destination id=%s network error: %s", destination.id, e
        )
        return SlackDeliveryResult(ok=False, status_code=None, detail=str(e))

    ok = 200 <= response.status_code < 300
    detail = None if ok else response.text[:300]
    if not ok:
        logger.warning(
            "slack: destination id=%s returned %s: %s",
            destination.id,
            response.status_code,
            detail,
        )
    return SlackDeliveryResult(ok=ok, status_code=response.status_code, detail=detail)


def build_card_blocks(
    *,
    card: TriageCard,
    event: str,
    card_url: str,
    repo_full_name: str,
    lead_report_text: str | None = None,
) -> list[dict[str, Any]]:
    """Build the Block Kit body for a card notification."""
    heading = _event_heading(event)
    title = _card_title(card, repo_full_name)
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{heading} {title}"[:150]},
        }
    ]

    context_bits: list[str] = []
    if card.severity:
        context_bits.append(f"{_severity_emoji(card.severity)} *{card.severity}*")
    if card.classification:
        if card.confidence is not None:
            context_bits.append(
                f"*{card.classification}* · conf {float(card.confidence):.2f}"
            )
        else:
            context_bits.append(f"*{card.classification}*")
    context_bits.append(f"source: `{card.source or 'github'}`")
    if card.status:
        context_bits.append(f"status: `{card.status}`")
    if context_bits:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": " · ".join(context_bits)}
                ],
            }
        )

    body_text = _body_snippet(card=card, lead_report_text=lead_report_text)
    if body_text:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body_text},
            }
        )

    suspected = _suspected_files_list(card)
    if suspected:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suspected files*\n{suspected}",
                },
            }
        )

    regression = _regression_summary(card, repo_full_name)
    if regression:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": regression},
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open in bugsift"},
                    "url": card_url,
                    "style": "primary",
                },
            ],
        }
    )
    return blocks


def _severity_emoji(severity: str) -> str:
    return {
        "blocker": "🚨",
        "high": "🔴",
        "medium": "🟡",
        "low": "⚪",
    }.get(severity.lower(), "")


def _event_heading(event: str) -> str:
    return {
        EVENT_NEW_CARD: "🆕 New card",
        EVENT_APPROVED: "✅ Approved",
        EVENT_REGRESSION: "⚠️ Likely regression",
    }.get(event, "bugsift")


def _card_title(card: TriageCard, repo_full_name: str) -> str:
    if card.source == "feedback":
        if card.github_issue_number:
            return f"{repo_full_name} #{card.github_issue_number}"
        return f"{repo_full_name} · user report"
    if card.issue_number is not None:
        return f"{repo_full_name} #{card.issue_number}"
    return repo_full_name


def _body_snippet(
    *, card: TriageCard, lead_report_text: str | None
) -> str | None:
    """Pick the best single snippet to show: rationale for github cards,
    first-report body for feedback cards. Clip hard — Slack blocks have
    a 3000-char limit, keep ourselves well under."""
    if card.source == "feedback" and lead_report_text:
        text = lead_report_text.strip()
    elif card.rationale:
        text = card.rationale.strip()
    elif card.draft_comment:
        text = card.draft_comment.strip()
    else:
        return None
    if not text:
        return None
    if len(text) > 600:
        text = text[:597].rstrip() + "…"
    return text


def _suspected_files_list(card: TriageCard) -> str | None:
    raw = card.suspected_files_json
    if not isinstance(raw, list) or not raw:
        return None
    lines: list[str] = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file_path", "")).strip()
        if not path:
            continue
        line_range = str(item.get("line_range", "")).strip()
        tag = f"`{path}:{line_range}`" if line_range else f"`{path}`"
        rationale = str(item.get("rationale", "")).strip()
        if rationale:
            lines.append(f"• {tag} — {rationale[:140]}")
        else:
            lines.append(f"• {tag}")
    return "\n".join(lines) if lines else None


def _regression_summary(card: TriageCard, repo_full_name: str) -> str | None:
    raw = card.regression_suspects_json
    if not isinstance(raw, list) or not raw:
        return None
    parts: list[str] = ["*Possible cause*"]
    for item in raw[:2]:
        if not isinstance(item, dict):
            continue
        short = str(item.get("short_sha", "")).strip()
        sha = str(item.get("commit_sha", "")).strip()
        msg = str(item.get("message_first_line", "")).strip()[:80]
        pr = item.get("pr_number")
        author = item.get("author_login") or item.get("author_name") or "someone"
        commit_link = (
            f"<https://github.com/{repo_full_name}/commit/{sha}|{short}>"
            if sha
            else short
        )
        pr_link = (
            f" · <https://github.com/{repo_full_name}/pull/{pr}|PR #{pr}>"
            if isinstance(pr, int)
            else ""
        )
        parts.append(f"• {commit_link} — {msg or '(no message)'}{pr_link} · {author}")
    return "\n".join(parts) if len(parts) > 1 else None


def _fallback_text(
    *, card: TriageCard, event: str, repo_full_name: str
) -> str:
    """Slack notification preview / screen-reader text. Not rendered when
    blocks are present but required by Slack's API."""
    return f"bugsift {_event_heading(event)} — {_card_title(card, repo_full_name)}"
