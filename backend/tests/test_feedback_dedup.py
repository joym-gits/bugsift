"""Tests for slice-3 duplicate-report collapsing."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TriageCard,
    User,
)
from bugsift.feedback import dedup


def _unit(dim: int, *nonzero_positions: tuple[int, float]) -> list[float]:
    """Build a sparse unit-ish vector for test fixtures. Keeps cosine
    similarity deterministic without dragging in numpy."""
    v = [0.0] * dim
    for pos, weight in nonzero_positions:
        v[pos] = weight
    # Normalize so cosine similarity is easy to reason about.
    mag = sum(x * x for x in v) ** 0.5
    if mag == 0:
        return v
    return [x / mag for x in v]


@pytest_asyncio.fixture
async def app_with_repo(session):
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
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    app = FeedbackApp(
        user_id=user.id,
        name="web",
        public_key="pk_test",
        default_repo_id=repo.id,
    )
    session.add(app)
    await session.commit()
    return app, repo


async def _seed_report_and_card(
    session,
    *,
    app: FeedbackApp,
    repo: Repo,
    body: str,
    vector: list[float],
    status: str = "pending",
    source: str = "feedback",
) -> tuple[FeedbackReport, TriageCard]:
    report = FeedbackReport(
        app_id=app.id,
        body_text=body,
        content_hash=body[:30],
        embedding_384=vector,
    )
    session.add(report)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        source=source,
        issue_number=None,
        feedback_report_ids_json=[report.id],
        status=status,
        classification="bug",
    )
    session.add(card)
    await session.flush()
    report.card_id = card.id
    await session.commit()
    return report, card


@pytest.mark.asyncio
async def test_near_duplicate_merges(session, app_with_repo) -> None:
    app, repo = app_with_repo
    vec_a = _unit(384, (0, 1.0), (1, 0.2))
    vec_b = _unit(384, (0, 1.0), (1, 0.21))  # cosine ~1.0

    original, card = await _seed_report_and_card(
        session, app=app, repo=repo, body="save is broken", vector=vec_a
    )
    new = FeedbackReport(
        app_id=app.id,
        body_text="Save button does nothing",
        content_hash="new",
    )
    session.add(new)
    await session.flush()

    match = await dedup.find_mergeable_card(session, report=new, vector=vec_b)
    assert match is not None
    assert match.merged_into_card_id == card.id
    assert match.similarity >= dedup.MERGE_SIMILARITY_THRESHOLD


@pytest.mark.asyncio
async def test_distinct_reports_do_not_merge(session, app_with_repo) -> None:
    app, repo = app_with_repo
    vec_a = _unit(384, (0, 1.0))
    vec_b = _unit(384, (10, 1.0))  # orthogonal → similarity ~0

    await _seed_report_and_card(
        session, app=app, repo=repo, body="save is broken", vector=vec_a
    )
    new = FeedbackReport(app_id=app.id, body_text="totally unrelated", content_hash="n")
    session.add(new)
    await session.flush()

    match = await dedup.find_mergeable_card(session, report=new, vector=vec_b)
    assert match is None


@pytest.mark.asyncio
async def test_does_not_cross_apps(session, app_with_repo) -> None:
    app, repo = app_with_repo
    # Second app owned by the same user.
    other_app = FeedbackApp(
        user_id=app.user_id, name="other", public_key="pk_other", default_repo_id=repo.id
    )
    session.add(other_app)
    await session.flush()

    vec = _unit(384, (0, 1.0))
    await _seed_report_and_card(
        session, app=other_app, repo=repo, body="same words", vector=vec
    )
    new = FeedbackReport(app_id=app.id, body_text="same words", content_hash="n")
    session.add(new)
    await session.flush()

    # New report is in ``app`` (not ``other_app``) — must not merge.
    match = await dedup.find_mergeable_card(session, report=new, vector=vec)
    assert match is None


@pytest.mark.asyncio
async def test_does_not_touch_posted_or_skipped_cards(session, app_with_repo) -> None:
    app, repo = app_with_repo
    vec = _unit(384, (0, 1.0))
    for closed_status in ("posted", "skipped"):
        _, _ = await _seed_report_and_card(
            session,
            app=app,
            repo=repo,
            body=f"old bug {closed_status}",
            vector=vec,
            status=closed_status,
        )
    new = FeedbackReport(app_id=app.id, body_text="same bug", content_hash="n")
    session.add(new)
    await session.flush()

    match = await dedup.find_mergeable_card(session, report=new, vector=vec)
    assert match is None


@pytest.mark.asyncio
async def test_attach_appends_to_card(session, app_with_repo) -> None:
    app, repo = app_with_repo
    vec = _unit(384, (0, 1.0))
    original, card = await _seed_report_and_card(
        session, app=app, repo=repo, body="save bug", vector=vec
    )

    new = FeedbackReport(
        app_id=app.id, body_text="save bug again", content_hash="n", embedding_384=vec
    )
    session.add(new)
    await session.flush()

    await dedup.attach_report_to_card(session, report=new, card_id=card.id)
    await session.commit()
    await session.refresh(card)
    await session.refresh(new)
    assert new.card_id == card.id
    assert card.feedback_report_ids_json == [original.id, new.id]
