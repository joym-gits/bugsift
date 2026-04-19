"""Collapse near-duplicate widget reports into a single triage card.

When a fresh ``FeedbackReport`` arrives, we embed its body with the
built-in local provider (384-dim) and look for an already-pending
feedback card in the same app whose underlying reports cluster near the
new embedding. If the best match is above
:data:`MERGE_SIMILARITY_THRESHOLD`, we attach the new report to that
card instead of spawning a new pipeline run — saving both LLM cost and
dashboard clutter.

Similarity is measured as cosine similarity on pgvector (``1 - <=>``).
Threshold is conservative on purpose: false splits (two cards for one
bug) are mild UX annoyance, false merges (two bugs collapsed into one
card) hide distinct defects. Tuned against English bug-report text; we
can revisit once we have real usage data.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import FeedbackReport, TriageCard

logger = logging.getLogger(__name__)

# Cosine similarity above which two feedback reports are treated as
# "the same bug, different user". 0.82 is calibrated against bge-small
# on short bug-report text — low enough that paraphrases merge, high
# enough that distinct symptoms on the same page don't.
MERGE_SIMILARITY_THRESHOLD = 0.82


@dataclass(frozen=True)
class MergeResult:
    merged_into_card_id: int
    similarity: float


async def find_mergeable_card(
    session: AsyncSession,
    *,
    report: FeedbackReport,
    vector: list[float],
) -> MergeResult | None:
    """Return the best matching open feedback card if similarity is above
    the threshold, else ``None``.

    Only considers:
    - cards in the same ``app_id`` (feedback apps are isolated)
    - ``source='feedback'``, ``status='pending'`` (don't reopen
      posted/skipped cards)
    - other reports — never compares a report against itself

    Cosine similarity is computed in Python rather than via pgvector's
    ``<=>`` operator. At the cardinalities we expect (tens of open
    feedback cards per app, each with a handful of reports) the Python
    loop is negligible, and it keeps the dedup path working in SQLite
    test fixtures that don't speak pgvector. If per-app counts grow into
    thousands we can bolt the ivfflat query back on as a fast path.
    """
    if not vector:
        return None
    stmt = (
        select(FeedbackReport.card_id, FeedbackReport.embedding_384)
        .join(TriageCard, TriageCard.id == FeedbackReport.card_id)
        .where(
            FeedbackReport.app_id == report.app_id,
            FeedbackReport.id != report.id,
            FeedbackReport.embedding_384.is_not(None),
            TriageCard.source == "feedback",
            TriageCard.status == "pending",
        )
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None

    best_card_id: int | None = None
    best_similarity = -1.0
    for card_id, candidate_vector in rows:
        if candidate_vector is None:
            continue
        sim = _cosine(vector, list(candidate_vector))
        if sim > best_similarity:
            best_similarity = sim
            best_card_id = int(card_id)

    if best_card_id is None or best_similarity < MERGE_SIMILARITY_THRESHOLD:
        return None
    return MergeResult(merged_into_card_id=best_card_id, similarity=best_similarity)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


async def attach_report_to_card(
    session: AsyncSession,
    *,
    report: FeedbackReport,
    card_id: int,
) -> TriageCard:
    """Append ``report.id`` to the card's ``feedback_report_ids_json``
    array and link ``report.card_id``. Caller commits."""
    card = await session.get(TriageCard, card_id)
    if card is None:
        raise RuntimeError(f"card {card_id} vanished mid-merge")
    ids = list(card.feedback_report_ids_json or [])
    if report.id not in ids:
        ids.append(report.id)
    card.feedback_report_ids_json = ids
    report.card_id = card.id
    return card
