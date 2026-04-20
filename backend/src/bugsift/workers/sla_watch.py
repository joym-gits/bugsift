"""SLA breach watcher.

Runs as a background asyncio task inside each API process. Every 60
seconds each instance tries to acquire a short-lived Redis lock; the
single winner scans for pending cards whose SLA has elapsed, fires a
Slack notification on every matching user's destinations, and writes
an audit event. The lock + NX keeps multi-worker gunicorn from
duplicating notifications.

Kept out of the RQ worker queue on purpose — SLA alerting is
time-critical and shouldn't wait behind a long triage job.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.audit.log import record as audit_record
from bugsift.config import get_settings
from bugsift.db.models import TriageCard
from bugsift.db.session import SessionLocal

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SEC = 60
LOCK_KEY = "sla_watcher:lock"
LOCK_TTL_SEC = 55  # < interval so we never double-claim a window

_task: asyncio.Task | None = None


async def start() -> None:
    """Launch the watcher if the deployment runs API + Redis. Idempotent."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="sla-watcher")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # pragma: no cover
        pass
    _task = None


async def _loop() -> None:
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("sla-watcher: started (interval=%ss)", SCAN_INTERVAL_SEC)
    try:
        while True:
            try:
                acquired = await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SEC)
                if acquired:
                    await _scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("sla-watcher: iteration crashed; continuing")
            try:
                await asyncio.sleep(SCAN_INTERVAL_SEC)
            except asyncio.CancelledError:
                raise
    finally:
        await redis.aclose()
        logger.info("sla-watcher: stopped")


async def _scan_once() -> None:
    # Late import to avoid circulars (slack enqueue → workers → db).
    from bugsift.workers import enqueue as enqueue_jobs

    async with SessionLocal() as session:
        breaches = await _find_breaches(session)
        if not breaches:
            return
        now = datetime.now(timezone.utc)
        for card_id in breaches:
            card = await session.get(TriageCard, card_id)
            if card is None or card.status != "pending":
                continue
            card.sla_breach_alerted_at = now
            await audit_record(
                session,
                action="sla.breached",
                target_type="card",
                target_id=card.id,
                summary=(
                    f"SLA breached on card #{card.id}"
                    + (f" · {card.sla_minutes}m" if card.sla_minutes else "")
                ),
                metadata={
                    "severity": card.severity,
                    "classification": card.classification,
                    "sla_minutes": card.sla_minutes,
                },
            )
            try:
                enqueue_jobs.enqueue_slack_notification(card.id, "sla_breach")
            except Exception:
                logger.exception(
                    "sla-watcher: enqueue slack failed card_id=%s", card.id
                )
        await session.commit()
        logger.info("sla-watcher: flagged %d breach(es)", len(breaches))


async def _find_breaches(session: AsyncSession) -> list[int]:
    """Return ids of pending cards whose SLA window has elapsed and
    which haven't been alerted yet. Uses the partial index
    ``ix_triage_cards_pending_sla`` so the scan is cheap.
    """
    stmt = (
        select(TriageCard.id)
        .where(
            TriageCard.status == "pending",
            TriageCard.sla_minutes.is_not(None),
            TriageCard.sla_breach_alerted_at.is_(None),
            # created_at + (sla_minutes || 'minutes')::interval < now()
            text(
                "triage_cards.created_at + (triage_cards.sla_minutes || ' minutes')::interval "
                "< now()"
            ),
        )
        .limit(200)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
