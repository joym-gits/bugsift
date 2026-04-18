from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, LLMUsage, Repo, RepoConfig, User
from bugsift.usage import start_of_current_month_utc

router = APIRouter(prefix="/usage", tags=["usage"])


class RepoUsageOut(BaseModel):
    repo_id: int
    repo_full_name: str
    monthly_budget_usd: float
    spent_usd: float
    remaining_usd: float
    is_exhausted: bool


class MonthlyUsageResponse(BaseModel):
    month_start_utc: str
    total_spent_usd: float
    repos: list[RepoUsageOut]


@router.get("/this-month", response_model=MonthlyUsageResponse)
async def monthly_usage(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MonthlyUsageResponse:
    since = start_of_current_month_utc()

    # Per-repo spend joined with repos + configs, scoped to the current user.
    stmt = (
        select(
            Repo.id,
            Repo.full_name,
            RepoConfig.monthly_budget_usd,
            func.coalesce(
                func.sum(LLMUsage.cost_usd).filter(LLMUsage.created_at >= since),
                0,
            ).label("spent"),
        )
        .join(Installation, Repo.installation_id == Installation.id)
        .join(RepoConfig, RepoConfig.repo_id == Repo.id, isouter=True)
        .join(LLMUsage, LLMUsage.repo_id == Repo.id, isouter=True)
        .where(Installation.user_id == user.id)
        .group_by(Repo.id, Repo.full_name, RepoConfig.monthly_budget_usd)
        .order_by(Repo.full_name.asc())
    )
    rows = (await session.execute(stmt)).all()

    repos: list[RepoUsageOut] = []
    total = 0.0
    for repo_id, full_name, budget_raw, spent_raw in rows:
        budget = float(budget_raw) if budget_raw is not None else 10.0
        spent = float(spent_raw or 0.0)
        total += spent
        repos.append(
            RepoUsageOut(
                repo_id=repo_id,
                repo_full_name=full_name,
                monthly_budget_usd=budget,
                spent_usd=spent,
                remaining_usd=max(0.0, budget - spent),
                is_exhausted=spent >= budget,
            )
        )
    return MonthlyUsageResponse(
        month_start_utc=since.isoformat(),
        total_spent_usd=total,
        repos=repos,
    )
