"""Monthly LLM spend calculation per repo.

§6 of the brief: the orchestrator checks each repo's remaining monthly
budget before expensive pipeline steps. "Budget exhausted" means the cheap
steps (classify, comment) still run but dedup / retrieval / reproduction
are skipped and the card is flagged ``budget_limited=true``.

"Monthly" is UTC calendar month to keep us provider-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import LLMUsage


@dataclass(frozen=True)
class BudgetStatus:
    budget_usd: float
    spent_usd: float

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    @property
    def is_exhausted(self) -> bool:
        return self.spent_usd >= self.budget_usd


def start_of_current_month_utc(now: datetime | None = None) -> datetime:
    ref = (now or datetime.now(UTC)).astimezone(UTC)
    return ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def monthly_spend_usd(
    session: AsyncSession, repo_id: int, *, now: datetime | None = None
) -> float:
    """Sum of llm_usage.cost_usd since the start of the current UTC month."""
    since = start_of_current_month_utc(now)
    stmt = (
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0))
        .where(LLMUsage.repo_id == repo_id)
        .where(LLMUsage.created_at >= since)
    )
    value = (await session.execute(stmt)).scalar_one()
    return float(value)


async def budget_status_for_repo(
    session: AsyncSession, repo_id: int, budget_usd: float
) -> BudgetStatus:
    spent = await monthly_spend_usd(session, repo_id)
    return BudgetStatus(budget_usd=float(budget_usd), spent_usd=spent)
