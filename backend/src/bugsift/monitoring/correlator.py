"""Correlate a monitoring event's file path(s) against existing
TriageCard suspected files for the same repo.

Mirrors :func:`bugsift.regression.correlator.find_regression_suspects`'s
approach — Python-side set overlap rather than JSONB containment
operators, so behavior is identical on the SQLite test harness and on
Postgres. Heuristic is intentionally cautious: exact path equality
only, newest card first, capped at ``limit``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import MonitoringEvent, TriageCard

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 3
# How many recent cards to scan before giving up — bounds the query on
# repos with a long card history instead of pulling every row ever written.
CANDIDATE_SCAN_LIMIT = 200


async def correlate_event(
    session: AsyncSession, *, repo_id: int, file_paths: list[str], limit: int = DEFAULT_LIMIT
) -> list[TriageCard]:
    """Return up to ``limit`` recent :class:`TriageCard` rows for
    ``repo_id`` whose ``suspected_files_json`` overlaps ``file_paths``,
    newest first. Empty list if there are no file paths or no matches."""
    wanted = {p.strip() for p in file_paths if p and p.strip()}
    if not wanted:
        return []

    rows = (
        (
            await session.execute(
                select(TriageCard)
                .where(TriageCard.repo_id == repo_id, TriageCard.suspected_files_json.is_not(None))
                .order_by(TriageCard.created_at.desc())
                .limit(CANDIDATE_SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    matches: list[TriageCard] = []
    for card in rows:
        card_paths = {
            item.get("file_path")
            for item in (card.suspected_files_json or [])
            if isinstance(item, dict)
        }
        if card_paths & wanted:
            matches.append(card)
            if len(matches) >= limit:
                break

    if matches:
        logger.info(
            "monitoring correlator: repo_id=%s matched %d card(s) against %d path(s)",
            repo_id,
            len(matches),
            len(wanted),
        )
    return matches


async def mark_resolved_for_card(
    session: AsyncSession, *, card_id: int, resolution_status: str
) -> int:
    """Stamp every still-open :class:`MonitoringEvent` correlated to
    ``card_id`` as resolved. Called when a TriageCard reaches a
    terminal status (approved -> "posted", or "skipped") so the
    monitoring view reflects that the underlying issue was triaged —
    closes the analysis -> triage -> monitoring visibility loop.
    Returns the number of rows updated."""
    result = await session.execute(
        update(MonitoringEvent)
        .where(
            MonitoringEvent.correlated_card_id == card_id,
            MonitoringEvent.resolved_at.is_(None),
        )
        .values(resolved_at=datetime.now(UTC), resolution_status=resolution_status)
    )
    count = result.rowcount or 0
    if count:
        logger.info(
            "monitoring correlator: resolved %d event(s) for card_id=%s status=%s",
            count,
            card_id,
            resolution_status,
        )
    return count
