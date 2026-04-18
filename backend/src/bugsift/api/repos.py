from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, Repo, User

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
