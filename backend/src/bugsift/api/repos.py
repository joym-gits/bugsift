from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.api.webhooks import _fetch_installation_repos, _upsert_repos
from bugsift.db.models import Installation, Repo, User
from bugsift.workers import enqueue as enqueue_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["repos"])


class RepoResponse(BaseModel):
    id: int
    full_name: str
    default_branch: str
    primary_language: str | None
    indexing_status: str
    indexed_at: datetime | None


@router.get("", response_model=list[RepoResponse])
async def list_repos(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[RepoResponse]:
    stmt = (
        select(Repo)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Installation.user_id == user.id)
        .order_by(Repo.full_name.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        RepoResponse(
            id=r.id,
            full_name=r.full_name,
            default_branch=r.default_branch,
            primary_language=r.primary_language,
            indexing_status=r.indexing_status,
            indexed_at=r.indexed_at,
        )
        for r in rows
    ]


class HydrateResponse(BaseModel):
    added: int
    skipped: int
    installations: int


@router.post("/hydrate", response_model=HydrateResponse)
async def hydrate_repos(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> HydrateResponse:
    """Re-query GitHub for every repo attached to this user's installations
    and add any that aren't already in the DB. Useful when an install
    webhook arrived without its ``repositories`` array populated (a real
    GitHub payload quirk).
    """
    installations = (
        await session.execute(
            select(Installation).where(Installation.user_id == user.id)
        )
    ).scalars().all()

    added = 0
    skipped = 0
    newly_added_repo_ids: list[int] = []
    for install in installations:
        repos_payload = await _fetch_installation_repos(
            session, install.github_installation_id
        )
        if not repos_payload:
            continue
        new_repo_ids = await _upsert_repos(session, install, repos_payload)
        added += len(new_repo_ids)
        skipped += len(repos_payload) - len(new_repo_ids)
        newly_added_repo_ids.extend(new_repo_ids)

    await session.commit()
    # Kick off indexing + backfill for anything newly created. Backfill
    # replays existing open issues through the triage pipeline so the user
    # doesn't need to re-open issues just to see them in the dashboard.
    for repo_id in newly_added_repo_ids:
        enqueue_jobs.enqueue_index_repo(repo_id)
        enqueue_jobs.enqueue_backfill_open_issues(repo_id)
    logger.info(
        "hydrate: user_id=%s installations=%s added=%s",
        user.id,
        len(installations),
        added,
    )
    return HydrateResponse(
        added=added, skipped=skipped, installations=len(installations)
    )


class BackfillResponse(BaseModel):
    repo_id: int
    queued: bool


@router.post("/{repo_id}/backfill", response_model=BackfillResponse)
async def backfill_repo(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BackfillResponse:
    """Manually re-run the existing-issue backfill for one repo.

    Useful when the install webhook raced ahead of the App config being
    saved, or when the user wants to re-pull the open-issue list after
    changing something in the repo.
    """
    stmt = (
        select(Repo)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Repo.id == repo_id, Installation.user_id == user.id)
    )
    repo = (await session.execute(stmt)).scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="repo not found"
        )
    enqueue_jobs.enqueue_backfill_open_issues(repo.id)
    logger.info("backfill queued for repo_id=%s user_id=%s", repo.id, user.id)
    return BackfillResponse(repo_id=repo.id, queued=True)
