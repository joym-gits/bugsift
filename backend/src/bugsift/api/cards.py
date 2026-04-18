from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, Repo, TriageCard, User

router = APIRouter(prefix="/cards", tags=["cards"])


class CardResponse(BaseModel):
    id: int
    repo_full_name: str
    issue_number: int
    status: str
    classification: str | None
    created_at: datetime


@router.get("", response_model=list[CardResponse])
async def list_cards(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 50,
) -> list[CardResponse]:
    repo = aliased(Repo)
    install = aliased(Installation)
    stmt = (
        select(
            TriageCard.id,
            repo.full_name,
            TriageCard.issue_number,
            TriageCard.status,
            TriageCard.classification,
            TriageCard.created_at,
        )
        .join(repo, TriageCard.repo_id == repo.id)
        .join(install, repo.installation_id == install.id)
        .where(install.user_id == user.id)
        .order_by(TriageCard.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CardResponse(
            id=row.id,
            repo_full_name=row.full_name,
            issue_number=row.issue_number,
            status=row.status,
            classification=row.classification,
            created_at=row.created_at,
        )
        for row in rows
    ]
