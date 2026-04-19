from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.api.webhooks import _fetch_installation_repos, _upsert_repos
from bugsift.db.models import Installation, Repo, User

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
    for install in installations:
        repos_payload = await _fetch_installation_repos(
            session, install.github_installation_id
        )
        if not repos_payload:
            continue
        new_repo_ids = await _upsert_repos(session, install, repos_payload)
        added += len(new_repo_ids)
        skipped += len(repos_payload) - len(new_repo_ids)

    await session.commit()
    logger.info(
        "hydrate: user_id=%s installations=%s added=%s",
        user.id,
        len(installations),
        added,
    )
    return HydrateResponse(
        added=added, skipped=skipped, installations=len(installations)
    )
