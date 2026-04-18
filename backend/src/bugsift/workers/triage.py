"""Triage worker jobs.

In Phase 3 these are stubs: an ``issues.opened`` webhook enqueues
:func:`process_issue_opened`, which writes a pending ``triage_cards`` row
with the raw payload. The real pipeline lands in Phase 5 onwards.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from bugsift.db.models import Repo, TriageCard
from bugsift.db.session import SessionLocal

logger = logging.getLogger(__name__)


def process_issue_opened(payload: dict[str, Any]) -> None:
    """RQ entrypoint. Sync wrapper over async DB work."""
    asyncio.run(_process_issue_opened(payload))


async def _process_issue_opened(payload: dict[str, Any]) -> None:
    issue = payload.get("issue") or {}
    repo_payload = payload.get("repository") or {}
    github_repo_id = repo_payload.get("id")
    issue_number = issue.get("number")
    if not github_repo_id or not issue_number:
        logger.warning("issues.opened payload missing repo or issue id; skipping")
        return

    async with SessionLocal() as session:
        repo = (
            await session.execute(select(Repo).where(Repo.github_repo_id == github_repo_id))
        ).scalar_one_or_none()
        if repo is None:
            logger.warning(
                "issues.opened for unknown repo github_repo_id=%s; skipping", github_repo_id
            )
            return

        existing = (
            await session.execute(
                select(TriageCard).where(
                    TriageCard.repo_id == repo.id, TriageCard.issue_number == issue_number
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "triage card already exists repo_id=%s issue_number=%s; skipping", repo.id, issue_number
            )
            return

        card = TriageCard(
            repo_id=repo.id,
            issue_number=issue_number,
            status="pending",
            raw_payload_json=payload,
        )
        session.add(card)
        await session.commit()
        logger.info("wrote stub triage card repo=%s issue=%s", repo.full_name, issue_number)
