"""Correlate a freshly-triaged card with recent pushes that touched the
same files.

The theory: if retrieval + reproduction landed on ``app/profile/save.py``
as a suspected file, and a commit merged yesterday touched exactly that
file, that commit is the single most useful thing to show the maintainer.
It doesn't *prove* regression — many bugs pre-date the push that exposed
them — but empirically it shortens "who broke this" to a near-instant
answer on a high fraction of real reports.

Inputs:
- a ``TriageState`` with ``suspected_files`` already populated
- the card's reference timestamp (use ``state.raw_payload``'s report
  creation if available, else ``datetime.now(UTC)`` — the orchestrator
  passes this in explicitly)

Output: up to ``limit`` :class:`RegressionSuspect` dataclasses, sorted
most-recent-first, each carrying which of the card's suspected paths
overlapped. Empty list if there are no matches, no suspected files, or
no recorded pushes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import PushEvent

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 14
DEFAULT_LIMIT = 3


@dataclass(frozen=True)
class RegressionSuspect:
    commit_sha: str
    short_sha: str
    message_first_line: str
    author_name: str | None
    author_login: str | None
    pushed_at: datetime
    pr_number: int | None
    ref: str | None
    overlapping_paths: list[str]


async def find_regression_suspects(
    session: AsyncSession,
    *,
    repo_id: int,
    suspected_paths: list[str],
    reference_time: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> list[RegressionSuspect]:
    """Pull PushEvents for this repo in the time window, return the ones
    that touched at least one path from ``suspected_paths``.

    Correlation is by path-level equality; ``pkg/foo.py`` in the card
    only matches ``pkg/foo.py`` in the push (not ``pkg/foo_test.py``).
    Heuristic is intentionally cautious: we'd rather surface nothing
    than surface false positives that erode trust in the feature.
    """
    if not suspected_paths:
        return []

    now = reference_time or datetime.now(UTC)
    cutoff = now - timedelta(days=window_days)

    stmt = (
        select(PushEvent)
        .where(
            PushEvent.repo_id == repo_id,
            PushEvent.pushed_at >= cutoff,
            PushEvent.pushed_at <= now,
        )
        .order_by(PushEvent.pushed_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()

    path_set = set(suspected_paths)
    suspects: list[RegressionSuspect] = []
    for row in rows:
        touched = row.touched_paths_json or []
        if not isinstance(touched, list):
            continue
        overlap = sorted(p for p in touched if p in path_set)
        if not overlap:
            continue
        suspects.append(
            RegressionSuspect(
                commit_sha=row.commit_sha,
                short_sha=row.commit_sha[:7],
                message_first_line=row.message_first_line or "",
                author_name=row.author_name,
                author_login=row.author_login,
                pushed_at=row.pushed_at,
                pr_number=row.pr_number,
                ref=row.ref,
                overlapping_paths=overlap,
            )
        )
        if len(suspects) >= limit:
            break

    if suspects:
        logger.info(
            "regression correlator: repo_id=%s matched %d push(es) against %d path(s)",
            repo_id,
            len(suspects),
            len(suspected_paths),
        )
    return suspects
