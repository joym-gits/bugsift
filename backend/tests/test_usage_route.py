from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import Installation, LLMUsage, Repo, RepoConfig, User


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
