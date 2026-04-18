from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from bugsift.api.cards import get_github_client_factory
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import Installation, Repo, TriageCard, User


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=1, github_login="maintainer", email=None)
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


@pytest_asyncio.fixture
async def pending_card(session, logged_in: User):
    install = Installation(github_installation_id=12345, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=67890,
        full_name="demo/widget",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        issue_number=7,
        status="pending",
        classification="bug",
        draft_comment="thanks for the report",
        proposed_labels_json=["bug"],
        proposed_action="comment_and_label",
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card, repo, install


def test_skip_marks_card_skipped(client, pending_card) -> None:
    card, *_ = pending_card
    r = client.post(f"/cards/{card.id}/skip")
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"


def test_edit_updates_draft(client, pending_card) -> None:
    card, *_ = pending_card
    r = client.patch(f"/cards/{card.id}", json={"draft_comment": "edited body"})
    assert r.status_code == 200
    assert r.json()["draft_comment"] == "edited body"


def test_approve_posts_comment_and_applies_labels(client, pending_card) -> None:
    card, repo, install = pending_card

    fake_client = AsyncMock()
    fake_client.post_issue_comment = AsyncMock(return_value={"id": 101})
    fake_client.add_labels = AsyncMock()
    fake_client.close_issue = AsyncMock()

    captured_installation_id: list[int] = []

    def factory(installation_id: int):
        captured_installation_id.append(installation_id)
        return fake_client

    client.app.dependency_overrides[get_github_client_factory] = lambda: factory
    try:
        r = client.post(f"/cards/{card.id}/approve")
    finally:
        client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "posted"
    assert body["final_comment"] == "thanks for the report"
    assert captured_installation_id == [install.github_installation_id]
    fake_client.post_issue_comment.assert_awaited_once()
    fake_client.add_labels.assert_awaited_once()
    fake_client.close_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_approve_already_posted_card(client, pending_card, session) -> None:
    card, *_ = pending_card
    card.status = "posted"
    await session.commit()
    r = client.post(f"/cards/{card.id}/approve")
    assert r.status_code == 409


def test_rerun_requires_pending(client, pending_card, session, monkeypatch) -> None:
    card, *_ = pending_card
    # Mock out the Redis-hitting enqueue so the route is unit-test clean.
    from bugsift.api import cards as cards_route

    captured: list[dict] = []
    monkeypatch.setattr(
        cards_route.enqueue_jobs,
        "enqueue_triage",
        lambda payload: captured.append(payload),
    )

    # Seed raw_payload_json so the endpoint has something to re-enqueue.
    import asyncio

    async def _seed() -> None:
        card.raw_payload_json = {
            "action": "opened",
            "issue": {"number": 7, "title": "boom", "body": "trace"},
            "repository": {"id": 67890, "full_name": "demo/widget"},
            "installation": {"id": 12345},
        }
        await session.commit()

    asyncio.get_event_loop().run_until_complete(_seed())

    r = client.post(f"/cards/{card.id}/rerun")
    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert len(captured) == 1
    assert captured[0]["issue"]["number"] == 7


def test_rerun_without_payload_returns_400(client, pending_card) -> None:
    card, *_ = pending_card
    # Default pending_card fixture has no raw_payload_json.
    r = client.post(f"/cards/{card.id}/rerun")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rerun_rejects_non_pending(client, pending_card, session) -> None:
    card, *_ = pending_card
    card.status = "posted"
    await session.commit()
    r = client.post(f"/cards/{card.id}/rerun")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_foreign_card_returns_404(client, logged_in, session) -> None:
    stranger = User(github_id=999, github_login="other", email=None)
    session.add(stranger)
    await session.flush()
    install = Installation(github_installation_id=22222, user_id=stranger.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=77777,
        full_name="other/repo",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    card = TriageCard(repo_id=repo.id, issue_number=1, status="pending")
    session.add(card)
    await session.commit()
    await session.refresh(card)
    assert client.post(f"/cards/{card.id}/skip").status_code == 404
