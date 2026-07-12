"""Post-card-write pipeline steps shared by every TriageCard producer.

Extracted once a third caller (analysis-findings, see
:mod:`bugsift.analysis.findings_cards`) needed the same routing-rules /
LLM-usage / Slack-notification logic already duplicated between
:mod:`bugsift.workers.triage` (source='github') and
:mod:`bugsift.workers.feedback_triage` (source='feedback'). Each
producer still owns its own ``_write_card`` — the input shape
(``TriageState`` vs. an analysis ``Finding``) differs too much to
unify usefully — but everything downstream of "a card now exists" is
identical regardless of source.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from bugsift.agent.state import LLMCallRecord
from bugsift.db.models import LLMUsage, TriageCard

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "anthropic"


async def apply_routing_rules(
    session, card: TriageCard, repo, *, log_label: str = ""
) -> Any:
    """Evaluate operator-defined routing rules for this card and merge
    the outcome into the card row. Mutations are additive: rule
    assignees layer on top of CODEOWNERS suggestions, rule labels on
    top of the LLM's proposed labels. Scalar fields (``sla_minutes``)
    are set last-match-wins.
    """
    from bugsift.rules import engine as rules_engine

    try:
        outcome = await rules_engine.evaluate_async(session, card, repo=repo)
    except Exception:
        logger.exception("rules engine failed for card_id=%s; continuing", card.id)
        return None
    if not outcome.any:
        return outcome

    if outcome.add_assignees:
        current = list(card.suggested_assignees_json or [])
        for login in outcome.add_assignees:
            if login not in current:
                current.append(login)
        card.suggested_assignees_json = current or None
    if outcome.add_labels:
        current = list(card.proposed_labels_json or [])
        for label in outcome.add_labels:
            if label not in current:
                current.append(label)
        card.proposed_labels_json = current or None
    if outcome.sla_minutes is not None:
        card.sla_minutes = outcome.sla_minutes
    logger.info(
        "triage_rules matched%s card_id=%s rules=%s sla=%s assignees=%s labels=%s",
        log_label,
        card.id,
        outcome.matched_rule_ids,
        outcome.sla_minutes,
        outcome.add_assignees,
        outcome.add_labels,
    )
    return outcome


def record_llm_usage(
    session,
    *,
    repo_id: int,
    card_id: int | None,
    calls: list[LLMCallRecord],
    provider: str = DEFAULT_PROVIDER,
    analysis_id: int | None = None,
) -> None:
    """Write one :class:`LLMUsage` row per LLM call. ``card_id`` is
    ``None`` for analysis-run calls that don't map 1:1 to a single card
    (one findings pass can produce N cards) — ``analysis_id`` is the
    correct join key for those instead."""
    for call in calls:
        session.add(
            LLMUsage(
                repo_id=repo_id,
                card_id=card_id,
                analysis_id=analysis_id,
                provider=provider,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                cost_usd=Decimal(f"{call.cost_usd:.6f}"),
                duration_ms=call.duration_ms,
                step_name=call.step,
            )
        )


def fire_slack_events(card: TriageCard, *, regression_suspects: list, rule_outcome=None) -> None:
    """Enqueue slack notifications per card event. Safe to call on every
    triage run — the worker fans out to destinations and applies per-
    destination event filters. Rule-driven destinations (the outcome
    of :mod:`bugsift.rules.engine`) are additive on top of the user's
    default event filters."""
    from bugsift.workers import enqueue as enqueue_jobs

    try:
        enqueue_jobs.enqueue_slack_notification(card.id, "new_card")
        if regression_suspects:
            enqueue_jobs.enqueue_slack_notification(card.id, "regression")
        if rule_outcome is not None:
            for dest_id in rule_outcome.notify_slack_destination_ids:
                enqueue_jobs.enqueue_slack_notification(
                    card.id, "new_card", destination_id=dest_id
                )
    except Exception:
        logger.exception("slack: enqueue failed for card_id=%s; continuing", card.id)
