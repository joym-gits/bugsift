"""Tests for the monitoring-event -> TriageCard correlator.

Mirrors tests/test_regression_correlator.py's shape: overlap math,
no-match cases, and limit/ordering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bugsift.db.models import Installation, Repo, TriageCard, User
from bugsift.monitoring.correlator import correlate_event


async def _seed_repo(session) -> Repo:
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


async def _card(
    session, repo: Repo, *, files: list[str], created_at: datetime | None = None
) -> TriageCard:
    card = TriageCard(
        repo_id=repo.id,
        source="analysis",
        status="pending",
        suspected_files_json=[{"file_path": f, "line_range": "1", "rationale": "x"} for f in files],
    )
    if created_at is not None:
        card.created_at = created_at
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card


@pytest.mark.asyncio
async def test_matching_path_surfaces_card(session):
    repo = await _seed_repo(session)
    card = await _card(session, repo, files=["backend/app.py"])

    matches = await correlate_event(session, repo_id=repo.id, file_paths=["backend/app.py"])
    assert [m.id for m in matches] == [card.id]


@pytest.mark.asyncio
async def test_non_overlapping_path_is_ignored(session):
    repo = await _seed_repo(session)
    await _card(session, repo, files=["backend/other.py"])

    matches = await correlate_event(session, repo_id=repo.id, file_paths=["backend/app.py"])
    assert matches == []


@pytest.mark.asyncio
async def test_empty_file_paths_returns_empty(session):
    repo = await _seed_repo(session)
    await _card(session, repo, files=["backend/app.py"])

    matches = await correlate_event(session, repo_id=repo.id, file_paths=[])
    assert matches == []


@pytest.mark.asyncio
async def test_cards_without_suspected_files_are_skipped(session):
    repo = await _seed_repo(session)
    card = TriageCard(repo_id=repo.id, source="github", status="pending")
    session.add(card)
    await session.commit()

    matches = await correlate_event(session, repo_id=repo.id, file_paths=["backend/app.py"])
    assert matches == []


@pytest.mark.asyncio
async def test_limit_is_respected_and_newest_first(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    cards = [
        await _card(session, repo, files=["backend/app.py"], created_at=now - timedelta(hours=i))
        for i in range(5)
    ]

    matches = await correlate_event(
        session, repo_id=repo.id, file_paths=["backend/app.py"], limit=3
    )
    assert len(matches) == 3
    # Newest-created first.
    assert [m.id for m in matches] == [c.id for c in cards][:3]


@pytest.mark.asyncio
async def test_other_repos_cards_are_not_matched(session):
    repo_a = await _seed_repo(session)
    user_b = User(github_id=2, github_login="other", email=None)
    session.add(user_b)
    await session.flush()
    install_b = Installation(github_installation_id=2, user_id=user_b.id)
    session.add(install_b)
    await session.flush()
    repo_b = Repo(
        installation_id=install_b.id,
        github_repo_id=2,
        full_name="acme/other",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo_b)
    await session.commit()
    await session.refresh(repo_b)

    await _card(session, repo_b, files=["backend/app.py"])

    matches = await correlate_event(session, repo_id=repo_a.id, file_paths=["backend/app.py"])
    assert matches == []
