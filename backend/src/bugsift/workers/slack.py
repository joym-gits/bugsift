"""Slack notification worker.

Runs out of the ``default`` queue. Takes a ``card_id`` + ``event``
string, fetches the owning user's Slack destinations, gates each one
on its event flags, and delivers a Block Kit message via HTTP POST.

Fan-out (one card → N destinations) is done here, not at the enqueue
site, so the triage workers only need to enqueue once per event and
don't have to know how many destinations the user has configured.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from bugsift.config import get_settings
from bugsift.db.models import (
    FeedbackReport,
    Installation,
    Repo,
    SlackDestination,
    TriageCard,
)
from bugsift.db.session import SessionLocal
from bugsift.slack import notifier

logger = logging.getLogger(__name__)


def notify_card_event(
    card_id: int, event: str, destination_id: int | None = None
) -> None:
    asyncio.run(_notify_card_event(card_id, event, destination_id))


async def _notify_card_event(
    card_id: int, event: str, destination_id: int | None
) -> None:
    async with SessionLocal() as session:
        card = await session.get(TriageCard, card_id)
        if card is None:
            logger.info("slack: card_id=%s not found; dropping notify", card_id)
            return

        repo = await session.get(Repo, card.repo_id)
        if repo is None:
            logger.info("slack: repo gone for card_id=%s; dropping", card_id)
            return
        install = await session.get(Installation, repo.installation_id)
        if install is None or install.user_id is None:
            logger.info(
                "slack: installation unlinked for card_id=%s; dropping", card_id
            )
            return

        # A routing rule can target a specific destination regardless
        # of its event filter. Load that one destination and bypass
        # ``should_notify`` for it; otherwise fan out to every
        # destination the user owns.
        if destination_id is not None:
            dest = await session.get(SlackDestination, destination_id)
            destinations = (
                [dest] if dest and dest.user_id == install.user_id else []
            )
        else:
            destinations = (
                await session.execute(
                    select(SlackDestination).where(
                        SlackDestination.user_id == install.user_id
                    )
                )
            ).scalars().all()
        if not destinations:
            return

        lead_report_text = await _lead_report_text(session, card)

        public_url = get_settings().public_url.rstrip("/")
        card_url = f"{public_url}/dashboard"

        fired = 0
        for dest in destinations:
            # Rule-targeted notifications bypass the per-destination
            # event filter — the operator already chose to route *this*
            # card to *this* channel.
            if destination_id is None and not notifier.should_notify(dest, event):
                continue
            try:
                result = await notifier.post_card_event(
                    dest,
                    card=card,
                    event=event,
                    card_url=card_url,
                    repo_full_name=repo.full_name,
                    lead_report_text=lead_report_text,
                )
            except Exception:
                logger.exception(
                    "slack: post crashed for destination id=%s card_id=%s event=%s",
                    dest.id,
                    card_id,
                    event,
                )
                continue
            if result.ok:
                fired += 1
        logger.info(
            "slack: card_id=%s event=%s fired %d/%d destinations",
            card_id,
            event,
            fired,
            len(destinations),
        )


async def _lead_report_text(session, card: TriageCard) -> str | None:
    """For feedback-sourced cards, return the first attached report's
    body so the Slack message shows what the user actually said. GitHub
    cards fall back to rationale / draft_comment inside the notifier."""
    if card.source != "feedback":
        return None
    ids = card.feedback_report_ids_json or []
    if not isinstance(ids, list) or not ids:
        return None
    try:
        first_id = int(ids[0])
    except (TypeError, ValueError):
        return None
    report = await session.get(FeedbackReport, first_id)
    return report.body_text if report else None
