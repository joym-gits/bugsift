"""Weekly-digest compute for a feedback app.

Given an app + period bounds, produce:

- **Report count** in the window, plus the count in the previous
  window for week-over-week trend.
- **Clusters** — greedy agglomerative grouping over the stored 384-d
  report embeddings, cosine-similarity threshold
  :data:`CLUSTER_SIMILARITY_THRESHOLD`. The biggest N (size ≥ 2)
  surface as "patterns"; singletons are dropped as noise.
- **Top suspected files** — union of ``suspected_files_json`` across
  cards produced in the window, ranked by how many cards referenced
  the file.
- **Severity breakdown** — counts by severity (blocker/high/medium/
  low/none) across those cards.

Kept in Python (not pgvector SQL) for the same reason as
:mod:`bugsift.feedback.dedup` — reports per app per week are counted
in the tens/hundreds, not thousands; Python cosine keeps tests honest
against the SQLite fixture and the logic stays readable.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import FeedbackApp, FeedbackReport, TriageCard

logger = logging.getLogger(__name__)

CLUSTER_SIMILARITY_THRESHOLD = 0.80
MAX_CLUSTERS = 10
MIN_CLUSTER_SIZE = 2
MAX_REPRESENTATIVE_CHARS = 400
MAX_TOP_FILES = 10


@dataclass
class Cluster:
    report_ids: list[int] = field(default_factory=list)
    card_ids: list[int] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    _sum: list[float] = field(default_factory=list)

    def size(self) -> int:
        return len(self.report_ids)

    def centroid(self) -> list[float]:
        if not self._sum:
            return []
        n = float(len(self.report_ids))
        return [x / n for x in self._sum]

    def representative(self) -> str:
        if not self.bodies:
            return ""
        # Pick the longest body as canonical — longer usually means more
        # self-contained, less "it broke".
        longest = max(self.bodies, key=len)
        cleaned = " ".join(longest.split())
        if len(cleaned) > MAX_REPRESENTATIVE_CHARS:
            cleaned = cleaned[: MAX_REPRESENTATIVE_CHARS - 1].rstrip() + "…"
        return cleaned


@dataclass
class DigestResult:
    period_start: datetime
    period_end: datetime
    report_count: int
    previous_report_count: int
    clusters: list[dict]
    top_files: list[dict]
    severity_breakdown: dict[str, int]


async def compute_digest(
    session: AsyncSession,
    *,
    app: FeedbackApp,
    period_start: datetime,
    period_end: datetime,
) -> DigestResult:
    reports = await _load_reports(session, app_id=app.id, start=period_start, end=period_end)
    previous_count = await _count_reports(
        session,
        app_id=app.id,
        start=period_start - (period_end - period_start),
        end=period_start,
    )

    clusters = _cluster_reports(reports)
    top_files = await _top_suspected_files(session, app_id=app.id, reports=reports)
    severity_breakdown = await _severity_breakdown(
        session, reports=reports
    )

    return DigestResult(
        period_start=period_start,
        period_end=period_end,
        report_count=len(reports),
        previous_report_count=previous_count,
        clusters=[_serialize_cluster(c) for c in clusters],
        top_files=top_files,
        severity_breakdown=severity_breakdown,
    )


async def _load_reports(
    session: AsyncSession, *, app_id: int, start: datetime, end: datetime
) -> list[FeedbackReport]:
    rows = (
        await session.execute(
            select(FeedbackReport)
            .where(
                FeedbackReport.app_id == app_id,
                FeedbackReport.created_at >= start,
                FeedbackReport.created_at < end,
            )
            .order_by(FeedbackReport.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def _count_reports(
    session: AsyncSession, *, app_id: int, start: datetime, end: datetime
) -> int:
    from sqlalchemy import func as _f

    count = (
        await session.execute(
            select(_f.count(FeedbackReport.id)).where(
                FeedbackReport.app_id == app_id,
                FeedbackReport.created_at >= start,
                FeedbackReport.created_at < end,
            )
        )
    ).scalar_one()
    return int(count or 0)


def _cluster_reports(reports: Iterable[FeedbackReport]) -> list[Cluster]:
    """Greedy single-pass clustering: for each report, attach to the
    best-matching existing cluster (if above threshold), else start a
    new one. Centroid is the running mean of member embeddings."""
    clusters: list[Cluster] = []
    for r in reports:
        vec = r.embedding_384
        if vec is None:
            continue
        # pgvector rows come back as a list already; coerce defensively.
        vector = [float(x) for x in list(vec)]
        best_idx = -1
        best_sim = -1.0
        for idx, c in enumerate(clusters):
            sim = _cosine(vector, c.centroid())
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
        if best_idx >= 0 and best_sim >= CLUSTER_SIMILARITY_THRESHOLD:
            c = clusters[best_idx]
            c.report_ids.append(r.id)
            if r.card_id is not None:
                c.card_ids.append(r.card_id)
            c.bodies.append(r.body_text or "")
            if not c._sum:
                c._sum = list(vector)
            else:
                for i, v in enumerate(vector):
                    c._sum[i] += v
        else:
            new_cluster = Cluster()
            new_cluster.report_ids = [r.id]
            if r.card_id is not None:
                new_cluster.card_ids = [r.card_id]
            new_cluster.bodies = [r.body_text or ""]
            new_cluster._sum = list(vector)
            clusters.append(new_cluster)

    meaningful = [c for c in clusters if c.size() >= MIN_CLUSTER_SIZE]
    meaningful.sort(key=lambda c: c.size(), reverse=True)
    return meaningful[:MAX_CLUSTERS]


def _serialize_cluster(c: Cluster) -> dict:
    # Dedupe card ids while preserving order of first occurrence.
    seen: set[int] = set()
    ordered_cards: list[int] = []
    for cid in c.card_ids:
        if cid in seen:
            continue
        seen.add(cid)
        ordered_cards.append(cid)
    return {
        "size": c.size(),
        "representative": c.representative(),
        "report_ids": list(c.report_ids),
        "card_ids": ordered_cards,
    }


async def _top_suspected_files(
    session: AsyncSession,
    *,
    app_id: int,
    reports: list[FeedbackReport],
) -> list[dict]:
    """Count file paths mentioned across the cards linked to the
    window's reports. We query via card_ids rather than time, so a
    card triaged slightly outside the window still counts if one of
    its reports landed in-window."""
    card_ids = sorted({r.card_id for r in reports if r.card_id is not None})
    if not card_ids:
        return []
    rows = (
        await session.execute(
            select(TriageCard.id, TriageCard.suspected_files_json).where(
                TriageCard.id.in_(card_ids)
            )
        )
    ).all()
    counter: Counter[str] = Counter()
    for _, suspected in rows:
        if not isinstance(suspected, list):
            continue
        paths_this_card: set[str] = set()
        for item in suspected:
            if not isinstance(item, dict):
                continue
            path = str(item.get("file_path", "")).strip()
            if path:
                paths_this_card.add(path)
        for path in paths_this_card:
            counter[path] += 1
    return [
        {"file_path": path, "card_count": count}
        for path, count in counter.most_common(MAX_TOP_FILES)
    ]


async def _severity_breakdown(
    session: AsyncSession, *, reports: list[FeedbackReport]
) -> dict[str, int]:
    card_ids = sorted({r.card_id for r in reports if r.card_id is not None})
    if not card_ids:
        return {}
    rows = (
        await session.execute(
            select(TriageCard.severity).where(TriageCard.id.in_(card_ids))
        )
    ).all()
    counter: Counter[str] = Counter()
    for (severity,) in rows:
        key = severity or "none"
        counter[key] += 1
    return dict(counter)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def current_weekly_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the [Monday 00:00 UTC, next Monday 00:00 UTC) window that
    contains ``now``. Sunday night falls in the week we're already
    summarising rather than rolling over mid-report."""
    now = now or datetime.now(UTC)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday, monday + timedelta(days=7)
