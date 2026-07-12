from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import Installation, LLMUsage, Repo, RepoAnalysis, RepoConfig, User


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    client.app.dependency_overrides[get_optional_user] = _fake_user
    yield user
    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_optional_user, None)


async def _seed_repo(session, user: User, *, name: str, budget: float = 10.0) -> Repo:
    install = Installation(github_installation_id=hash(name) & 0x7FFFFFFF, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=hash(name) & 0x7FFFFFF,
        full_name=name,
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.flush()
    session.add(
        RepoConfig(repo_id=repo.id, monthly_budget_usd=Decimal(f"{budget:.2f}"))
    )
    await session.commit()
    return repo


def test_usage_requires_login(client) -> None:
    assert client.get("/usage/this-month").status_code == 401


@pytest.mark.asyncio
async def test_usage_returns_per_repo(client, session, logged_in) -> None:
    repo_a = await _seed_repo(session, logged_in, name="u/a", budget=5.0)
    repo_b = await _seed_repo(session, logged_in, name="u/b", budget=10.0)
    session.add(
        LLMUsage(
            repo_id=repo_a.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("1.25"),
            step_name="classify",
        )
    )
    session.add(
        LLMUsage(
            repo_id=repo_b.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("0.5"),
            step_name="comment",
        )
    )
    await session.commit()

    body = client.get("/usage/this-month").json()
    assert round(body["total_spent_usd"], 2) == 1.75
    by_repo = {r["repo_full_name"]: r for r in body["repos"]}
    assert round(by_repo["u/a"]["spent_usd"], 2) == 1.25
    assert by_repo["u/a"]["is_exhausted"] is False
    assert round(by_repo["u/b"]["remaining_usd"], 2) == 9.50


@pytest.mark.asyncio
async def test_usage_marks_exhausted(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in, name="u/broke", budget=1.0)
    session.add(
        LLMUsage(
            repo_id=repo.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("1.0"),
            step_name="classify",
        )
    )
    await session.commit()
    body = client.get("/usage/this-month").json()
    repo_row = next(r for r in body["repos"] if r["repo_full_name"] == "u/broke")
    assert repo_row["is_exhausted"] is True
    assert repo_row["remaining_usd"] == 0.0


@pytest.mark.asyncio
async def test_usage_only_includes_current_users_repos(
    client, session, logged_in
) -> None:
    await _seed_repo(session, logged_in, name="u/mine")
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    await _seed_repo(session, stranger, name="someone/else")

    body = client.get("/usage/this-month").json()
    names = {r["repo_full_name"] for r in body["repos"]}
    assert names == {"u/mine"}


def test_usage_history_requires_login(client) -> None:
    assert client.get("/usage/history").status_code == 401


@pytest.mark.asyncio
async def test_usage_history_buckets_by_month(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in, name="u/history")
    session.add(
        LLMUsage(
            repo_id=repo.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("1.00"),
            step_name="analysis_synthesis",
            created_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
    )
    session.add(
        LLMUsage(
            repo_id=repo.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=Decimal("2.50"),
            step_name="analysis_findings",
            created_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
    )
    await session.commit()

    body = client.get("/usage/history?months=12").json()
    by_month = {p["month_start_utc"][:7]: p["spent_usd"] for p in body if p["repo_id"] == repo.id}
    assert round(by_month["2026-03"], 2) == 1.00
    assert round(by_month["2026-04"], 2) == 2.50


@pytest.mark.asyncio
async def test_usage_history_scoped_to_owned_repos(client, session, logged_in) -> None:
    mine = await _seed_repo(session, logged_in, name="u/mine-history")
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    theirs = await _seed_repo(session, stranger, name="someone/history")
    for repo in (mine, theirs):
        session.add(
            LLMUsage(
                repo_id=repo.id,
                provider="anthropic",
                model="claude-sonnet-4-6",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal("1.0"),
                step_name="analysis_synthesis",
            )
        )
    await session.commit()

    body = client.get("/usage/history").json()
    assert {p["repo_id"] for p in body} == {mine.id}

    assert client.get(f"/usage/history?repo_id={theirs.id}").status_code == 404


@pytest.mark.asyncio
async def test_usage_by_run_returns_cost_and_duration_breakdown(
    client, session, logged_in
) -> None:
    repo = await _seed_repo(session, logged_in, name="u/by-run")
    started = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    generated = datetime(2026, 4, 1, 12, 0, 5, tzinfo=UTC)
    analysis = RepoAnalysis(
        repo_id=repo.id,
        branch="main",
        status="ready",
        started_at=started,
        generated_at=generated,
    )
    session.add(analysis)
    await session.flush()
    session.add(
        LLMUsage(
            repo_id=repo.id,
            analysis_id=analysis.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=10,
            completion_tokens=10,
            cost_usd=Decimal("0.10"),
            duration_ms=200,
            step_name="analysis_synthesis",
        )
    )
    session.add(
        LLMUsage(
            repo_id=repo.id,
            analysis_id=analysis.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=10,
            completion_tokens=10,
            cost_usd=Decimal("0.25"),
            duration_ms=300,
            step_name="analysis_findings",
        )
    )
    await session.commit()

    body = client.get(f"/usage/by-run?repo_id={repo.id}").json()
    assert len(body) == 1
    run = body[0]
    assert run["analysis_id"] == analysis.id
    assert run["branch"] == "main"
    assert round(run["total_cost_usd"], 2) == 0.35
    assert run["call_count"] == 2
    assert round(run["by_step"]["analysis_synthesis"], 2) == 0.10
    assert round(run["by_step"]["analysis_findings"], 2) == 0.25
    assert run["duration_ms"] == 5000


@pytest.mark.asyncio
async def test_usage_by_run_404_for_other_users_repo(client, session, logged_in) -> None:
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    theirs = await _seed_repo(session, stranger, name="someone/else-by-run")

    r = client.get(f"/usage/by-run?repo_id={theirs.id}")
    assert r.status_code == 404
