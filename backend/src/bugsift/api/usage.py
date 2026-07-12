from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, LLMUsage, Repo, RepoAnalysis, RepoConfig, User
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


def _month_start_n_back(months_back: int, now: datetime | None = None) -> datetime:
    ref = now or datetime.now(UTC)
    total = ref.year * 12 + (ref.month - 1) - months_back
    year, month0 = divmod(total, 12)
    return datetime(year, month0 + 1, 1, tzinfo=UTC)


async def _owned_repo(session: AsyncSession, user: User, repo_id: int) -> Repo:
    repo = (
        await session.execute(
            select(Repo)
            .join(Installation, Repo.installation_id == Installation.id)
            .where(Repo.id == repo_id, Installation.user_id == user.id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    return repo


class UsageHistoryPoint(BaseModel):
    month_start_utc: str
    repo_id: int
    repo_full_name: str
    spent_usd: float


@router.get("/history", response_model=list[UsageHistoryPoint])
async def usage_history(
    repo_id: int | None = None,
    months: int = 6,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[UsageHistoryPoint]:
    """Monthly spend time series, scoped to the caller's repos.
    ``months`` is clamped to [1, 24]. Bucketed in Python (not a
    Postgres-only date_trunc) so behavior matches on the sqlite test
    harness."""
    months = max(1, min(months, 24))
    if repo_id is not None:
        await _owned_repo(session, user, repo_id)
    cutoff = _month_start_n_back(months - 1)

    stmt = (
        select(Repo.id, Repo.full_name, LLMUsage.created_at, LLMUsage.cost_usd)
        .join(Installation, Repo.installation_id == Installation.id)
        .join(LLMUsage, LLMUsage.repo_id == Repo.id)
        .where(Installation.user_id == user.id, LLMUsage.created_at >= cutoff)
    )
    if repo_id is not None:
        stmt = stmt.where(Repo.id == repo_id)
    rows = (await session.execute(stmt)).all()

    buckets: dict[tuple[int, int, int], float] = {}
    names: dict[int, str] = {}
    for rid, full_name, created_at, cost in rows:
        names[rid] = full_name
        key = (rid, created_at.year, created_at.month)
        buckets[key] = buckets.get(key, 0.0) + float(cost or 0.0)

    points = [
        UsageHistoryPoint(
            month_start_utc=datetime(year, month, 1, tzinfo=UTC).isoformat(),
            repo_id=rid,
            repo_full_name=names[rid],
            spent_usd=spent,
        )
        for (rid, year, month), spent in buckets.items()
    ]
    points.sort(key=lambda p: (p.month_start_utc, p.repo_full_name))
    return points


class UsageRunOut(BaseModel):
    analysis_id: int
    repo_id: int
    branch: str
    status: str
    started_at: str | None
    generated_at: str | None
    duration_ms: int | None
    total_cost_usd: float
    call_count: int
    by_step: dict[str, float]


@router.get("/by-run", response_model=list[UsageRunOut])
async def usage_by_run(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[UsageRunOut]:
    """Per-analysis-run cost/duration breakdown for one repo the caller
    owns, newest first."""
    repo = await _owned_repo(session, user, repo_id)

    analyses = (
        (
            await session.execute(
                select(RepoAnalysis)
                .where(RepoAnalysis.repo_id == repo.id)
                .order_by(RepoAnalysis.id.desc())
            )
        )
        .scalars()
        .all()
    )
    if not analyses:
        return []

    analysis_ids = [a.id for a in analyses]
    usage_rows = (
        await session.execute(
            select(LLMUsage.analysis_id, LLMUsage.step_name, LLMUsage.cost_usd).where(
                LLMUsage.analysis_id.in_(analysis_ids)
            )
        )
    ).all()

    by_step_per_run: dict[int, dict[str, float]] = {}
    call_counts: dict[int, int] = {}
    for aid, step, cost in usage_rows:
        steps = by_step_per_run.setdefault(aid, {})
        steps[step] = steps.get(step, 0.0) + float(cost or 0.0)
        call_counts[aid] = call_counts.get(aid, 0) + 1

    out: list[UsageRunOut] = []
    for a in analyses:
        by_step = by_step_per_run.get(a.id, {})
        duration_ms = None
        if a.started_at is not None and a.generated_at is not None:
            duration_ms = int((a.generated_at - a.started_at).total_seconds() * 1000)
        out.append(
            UsageRunOut(
                analysis_id=a.id,
                repo_id=a.repo_id,
                branch=a.branch,
                status=a.status,
                started_at=a.started_at.isoformat() if a.started_at else None,
                generated_at=a.generated_at.isoformat() if a.generated_at else None,
                duration_ms=duration_ms,
                total_cost_usd=sum(by_step.values()),
                call_count=call_counts.get(a.id, 0),
                by_step=by_step,
            )
        )
    return out
