"""Delta capture for feedback-loop learning.

Every approve/skip/edit path calls :func:`record_correction` so the
pipeline has real operator decisions to learn from on the next run.
Only non-trivial deltas are recorded — approving the pipeline's
suggestion unchanged doesn't teach the prompt anything, so it
doesn't get stored.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import CardCorrection, TriageCard, User

logger = logging.getLogger(__name__)

# Cap on the issue-context snippet we persist per correction — the
# retriever feeds it into prompts so a tight budget keeps later
# prompt bloat manageable.
CONTEXT_CHARS_MAX = 400


async def record_correction(
    session: AsyncSession,
    *,
    card: TriageCard,
    user: User | None,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    issue_title: str | None = None,
    issue_body: str | None = None,
) -> None:
    """Persist a single correction row. Best-effort: a row-write
    failure never blocks the card action that produced it.

    Skips trivial corrections where ``before == after`` — those carry
    no learning signal.
    """
    if _is_trivial(before, after):
        return
    try:
        row = CardCorrection(
            repo_id=card.repo_id,
            card_id=card.id,
            user_id=user.id if user else None,
            action=action,
            before_json=_coerce_json(before),
            after_json=_coerce_json(after),
            issue_context=_compact_context(issue_title, issue_body),
            classification=card.classification,
        )
        session.add(row)
        await session.flush()
    except Exception:  # pragma: no cover
        logger.exception(
            "corrections: failed to record action=%s card_id=%s", action, card.id
        )


def diff_approve(
    *,
    card: TriageCard,
    final_assignees: list[str] | None,
    final_labels: list[str] | None,
    final_comment: str | None,
) -> list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]]:
    """Return a list of ``(action, before, after)`` tuples for every
    meaningful divergence between what the pipeline suggested on the
    card and what the operator approved. Called from the approve
    handler; each tuple is then passed to :func:`record_correction`.
    """
    out: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []

    suggested_assignees = set(card.suggested_assignees_json or [])
    final_assignee_set = set(final_assignees or [])
    if suggested_assignees != final_assignee_set:
        out.append(
            (
                "override_assignees",
                {"assignees": sorted(suggested_assignees)},
                {"assignees": sorted(final_assignee_set)},
            )
        )

    suggested_labels = set(card.proposed_labels_json or [])
    final_label_set = set(final_labels or [])
    if suggested_labels != final_label_set:
        out.append(
            (
                "override_labels",
                {"labels": sorted(suggested_labels)},
                {"labels": sorted(final_label_set)},
            )
        )

    if final_comment is not None and final_comment.strip() != (card.draft_comment or "").strip():
        out.append(
            (
                "edit_comment",
                {"draft_comment": card.draft_comment},
                {"final_comment": final_comment},
            )
        )

    return out


def _is_trivial(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> bool:
    if before is None and after is None:
        return True
    return _coerce_json(before) == _coerce_json(after)


def _coerce_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalise list-valued fields so equality checks don't trip over
    tuple-vs-list or duplicate entries."""
    if value is None:
        return None
    out: dict[str, Any] = {}
    for k, v in value.items():
        if isinstance(v, (list, tuple, set)):
            out[k] = sorted({str(x) for x in v if x is not None})
        else:
            out[k] = v
    return out


def _compact_context(title: str | None, body: str | None) -> str | None:
    """Short excerpt of the issue — enough for the retriever to match
    a future issue against this correction without dragging the full
    body into every prompt."""
    parts = [p.strip() for p in (title, body) if p and p.strip()]
    if not parts:
        return None
    merged = "\n".join(parts)
    if len(merged) <= CONTEXT_CHARS_MAX:
        return merged
    return merged[: CONTEXT_CHARS_MAX - 1] + "…"
