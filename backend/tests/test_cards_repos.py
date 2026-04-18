from __future__ import annotations

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import Installation, Repo, TriageCard, User


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=77, github_login="maintainer", email="m@example.com")
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


async def _seed_repo_with_cards(session, user: User, repo_name: str, *cards: tuple[int, str]) -> Repo:
    install = Installation(github_installation_id=hash(repo_name) & 0x7FFFFFFF, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=hash(repo_name) & 0x7FFFFFF,
        full_name=repo_name,
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    for issue_number, classification in cards:
        session.add(
            TriageCard(
                repo_id=repo.id,
                issue_number=issue_number,
                status="pending",
                classification=classification,
            )
        )
    await session.commit()
    return repo


def test_lists_require_login(client) -> None:
    assert client.get("/cards").status_code == 401
    assert client.get("/repos").status_code == 401


@pytest.mark.asyncio
async def test_cards_and_repos_scoped_to_current_user(client, session, logged_in: User) -> None:
    await _seed_repo_with_cards(session, logged_in, "me/alpha", (1, "bug"), (2, "question"))

    # Seed a foreign user's repo that should NOT appear.
    other = User(github_id=999, github_login="stranger", email=None)
    session.add(other)
    await session.commit()
    await session.refresh(other)
    await _seed_repo_with_cards(session, other, "them/hidden", (99, "bug"))

    repos = client.get("/repos").json()
    assert [r["full_name"] for r in repos] == ["me/alpha"]

    cards = client.get("/cards").json()
    assert {(c["repo_full_name"], c["issue_number"]) for c in cards} == {
        ("me/alpha", 1),
        ("me/alpha", 2),
    }
