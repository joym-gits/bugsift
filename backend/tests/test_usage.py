from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bugsift.db.models import (
    Installation,
    LLMUsage,
    Repo,
    RepoConfig,
    User,
)
from bugsift.usage import (
    budget_status_for_repo,
    monthly_spend_usd,
    start_of_current_month_utc,
)


async def _seed_repo(session, *, repo_name: str = "o/r") -> Repo:
    user = User(github_id=1, github_login="u", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name=repo_name,
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.flush()
    session.add(
        RepoConfig(
            repo_id=repo.id,
            monthly_budget_usd=Decimal("10.00"),
        )
    )
    await session.commit()
    return repo


def _usage(repo_id: int, cost: float, *, created_at: datetime | None = None) -> LLMUsage:
    return LLMUsage(
        repo_id=repo_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=100,
        completion_tokens=30,
        cost_usd=Decimal(f"{cost:.6f}"),
        step_name="classify",
        created_at=created_at or datetime.now(UTC),
    )


async def test_no_rows_means_zero_spend(session) -> None:
    repo = await _seed_repo(session)
    assert await monthly_spend_usd(session, repo.id) == 0.0


async def test_sums_only_current_month(session) -> None:
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=15)
    session.add(_usage(repo.id, 5.00, created_at=last_month))
    session.add(_usage(repo.id, 1.25, created_at=now))
    session.add(_usage(repo.id, 0.75, created_at=now))
    await session.commit()
    assert round(await monthly_spend_usd(session, repo.id), 2) == 2.00


async def test_scoped_to_single_repo(session) -> None:
    repo = await _seed_repo(session)
    other_user = User(github_id=2, github_login="o", email=None)
    session.add(other_user)
    await session.flush()
    other_install = Installation(github_installation_id=2, user_id=other_user.id)
    session.add(other_install)
    await session.flush()
    other_repo = Repo(
        installation_id=other_install.id,
        github_repo_id=2,
        full_name="other/repo",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(other_repo)
    await session.flush()
    session.add(_usage(repo.id, 0.50))
    session.add(_usage(other_repo.id, 99.00))
    await session.commit()
    assert round(await monthly_spend_usd(session, repo.id), 2) == 0.50


async def test_budget_status_not_exhausted(session) -> None:
    repo = await _seed_repo(session)
    session.add(_usage(repo.id, 3.00))
    await session.commit()
    status = await budget_status_for_repo(session, repo.id, 10.00)
    assert status.is_exhausted is False
    assert status.remaining_usd == pytest.approx(7.00)


async def test_budget_status_exhausted(session) -> None:
    repo = await _seed_repo(session)
    session.add(_usage(repo.id, 10.00))
    await session.commit()
    status = await budget_status_for_repo(session, repo.id, 10.00)
    assert status.is_exhausted is True
    assert status.remaining_usd == 0.0


def test_start_of_month_is_day_one_utc() -> None:
    some_day = datetime(2026, 5, 17, 14, 30, 0, tzinfo=UTC)
    out = start_of_current_month_utc(some_day)
    assert out == datetime(2026, 5, 1, tzinfo=UTC)
