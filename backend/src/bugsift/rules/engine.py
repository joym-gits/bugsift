"""Routing-rules engine.

Runs after every card is written. All rules owned by the card's
installation owner are evaluated in priority ASC, id ASC order. Each
rule's ``match`` block is AND-combined (every condition must hold);
matching rules accumulate their ``action`` effects:

- ``assign``: union of suggested_assignees (extra logins layered on
  top of CODEOWNERS suggestions).
- ``add_labels``: union of proposed_labels.
- ``notify_slack`` (destination_id): appended to a list the caller
  emits side-effects for.
- ``sla_minutes``: last-match-wins (lower-priority rules override).
- ``escalate_to_pagerduty_integration_key``: last-match-wins.

Conditions supported:

- ``classification``: exact match on the LLM classification.
- ``severity``: exact match on the computed severity.
- ``source``: ``github`` | ``feedback``.
- ``repo_full_name_glob``: fnmatch-style glob against
  ``repo_full_name`` (e.g. ``my-org/*``).
- ``reproduction_verdict``: exact match.
- ``has_regression_suspects``: bool — card has ≥1 suspected-commit
  correlation.
- ``min_confidence``: float; card confidence ≥ value.
- ``proposed_action``: exact match (``comment-only`` / ``label`` /
  ``close`` / ``assign`` etc).

Unknown keys fail closed — the rule does not match, so operators
notice typos rather than getting accidentally-matched broad rules.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bugsift.db.models import Installation, Repo, TriageCard, TriageRule

logger = logging.getLogger(__name__)


@dataclass
class RuleOutcome:
    """What the engine decided — the caller mutates the card / fires
    side effects. Lists are additive; scalars are last-match-wins."""

    add_assignees: list[str] = field(default_factory=list)
    add_labels: list[str] = field(default_factory=list)
    notify_slack_destination_ids: list[int] = field(default_factory=list)
    sla_minutes: int | None = None
    pagerduty_integration_key: str | None = None
    matched_rule_ids: list[int] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(
            self.add_assignees
            or self.add_labels
            or self.notify_slack_destination_ids
            or self.sla_minutes is not None
            or self.pagerduty_integration_key
        )


def evaluate(session: Session, card: TriageCard, *, repo: Repo | None = None) -> RuleOutcome:
    """Sync-session variant (RQ worker path). See :func:`evaluate_async`
    for the async-session version used from HTTP handlers.
    """
    rules = _rules_for_card(session, card)
    if repo is None:
        repo = session.get(Repo, card.repo_id)
    return _apply_rules(rules, card, repo)


async def evaluate_async(session, card: TriageCard, *, repo: Repo | None = None) -> RuleOutcome:
    """Async version — used from request handlers / async workers."""
    rules = await _rules_for_card_async(session, card)
    if repo is None:
        repo = await session.get(Repo, card.repo_id)
    return _apply_rules(rules, card, repo)


def _rules_for_card(session: Session, card: TriageCard) -> list[TriageRule]:
    # Find the owner of the card (card → repo → installation → user).
    # If anything along the chain is missing, return no rules.
    repo = session.get(Repo, card.repo_id)
    if repo is None:
        return []
    install = session.get(Installation, repo.installation_id)
    if install is None or install.user_id is None:
        return []
    return list(
        session.execute(
            select(TriageRule)
            .where(
                TriageRule.user_id == install.user_id,
                TriageRule.enabled.is_(True),
            )
            .order_by(TriageRule.priority.asc(), TriageRule.id.asc())
        )
        .scalars()
    )


async def _rules_for_card_async(session, card: TriageCard) -> list[TriageRule]:
    repo = await session.get(Repo, card.repo_id)
    if repo is None:
        return []
    install = await session.get(Installation, repo.installation_id)
    if install is None or install.user_id is None:
        return []
    rows = (
        await session.execute(
            select(TriageRule)
            .where(
                TriageRule.user_id == install.user_id,
                TriageRule.enabled.is_(True),
            )
            .order_by(TriageRule.priority.asc(), TriageRule.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _apply_rules(
    rules: list[TriageRule], card: TriageCard, repo: Repo | None
) -> RuleOutcome:
    outcome = RuleOutcome()
    for rule in rules:
        if not _matches(rule.match_json or {}, card, repo):
            continue
        outcome.matched_rule_ids.append(rule.id)
        _merge_actions(outcome, rule.action_json or {})
    return outcome


def _matches(match: dict[str, Any], card: TriageCard, repo: Repo | None) -> bool:
    if not match:
        # Empty match block = match everything. Useful as a safety-net
        # rule at priority 999 that catches unclassified cards.
        return True
    for key, expected in match.items():
        if not _check_condition(key, expected, card, repo):
            return False
    return True


def _check_condition(
    key: str, expected: Any, card: TriageCard, repo: Repo | None
) -> bool:
    if key == "classification":
        return str(card.classification or "") == str(expected)
    if key == "severity":
        return str(card.severity or "") == str(expected)
    if key == "source":
        return str(card.source or "github") == str(expected)
    if key == "repo_full_name_glob":
        if repo is None:
            return False
        return fnmatch.fnmatch(repo.full_name, str(expected))
    if key == "reproduction_verdict":
        return str(card.reproduction_verdict or "") == str(expected)
    if key == "has_regression_suspects":
        suspects = card.regression_suspects_json or []
        has = bool(suspects) and len(list(suspects)) > 0
        return bool(expected) == has
    if key == "min_confidence":
        try:
            needed = float(expected)
        except (TypeError, ValueError):
            return False
        actual = float(card.confidence) if card.confidence is not None else 0.0
        return actual >= needed
    if key == "proposed_action":
        return str(card.proposed_action or "") == str(expected)
    # Unknown key → fail closed.
    logger.warning("triage_rule: unknown condition key=%s — rule will not match", key)
    return False


_ALLOWED_ACTION_KEYS = {
    "assign",
    "add_labels",
    "notify_slack",
    "sla_minutes",
    "escalate_to_pagerduty_integration_key",
}


def _merge_actions(outcome: RuleOutcome, action: dict[str, Any]) -> None:
    for key, value in action.items():
        if key not in _ALLOWED_ACTION_KEYS:
            logger.warning("triage_rule: unknown action key=%s — ignored", key)
            continue
        if key == "assign":
            for login in value or []:
                if not isinstance(login, str):
                    continue
                clean = login.strip().lstrip("@")
                if clean and clean not in outcome.add_assignees:
                    outcome.add_assignees.append(clean)
        elif key == "add_labels":
            for label in value or []:
                if not isinstance(label, str):
                    continue
                clean = label.strip()
                if clean and clean not in outcome.add_labels:
                    outcome.add_labels.append(clean)
        elif key == "notify_slack":
            try:
                dest_id = int(value)
            except (TypeError, ValueError):
                continue
            if dest_id not in outcome.notify_slack_destination_ids:
                outcome.notify_slack_destination_ids.append(dest_id)
        elif key == "sla_minutes":
            try:
                outcome.sla_minutes = max(1, int(value))
            except (TypeError, ValueError):
                pass
        elif key == "escalate_to_pagerduty_integration_key":
            if isinstance(value, str) and value.strip():
                outcome.pagerduty_integration_key = value.strip()
