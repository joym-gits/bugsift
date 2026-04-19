"""Tests for slice-2 feedback \u2192 triage pipeline.

- The adapter turns a ``FeedbackReport`` into a ``TriageState`` with a
  synthesised title, a body that merges context, and ``issue_number=0``.
- Ingest auto-enqueues the feedback triage job.
- Cards surfaced through the API include ``source`` + feedback report
  counts; ``/cards/{id}/reports`` returns the underlying rows.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from bugsift.agent.steps import ingest_feedback
from bugsift.api import feedback as feedback_route
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TriageCard,
    User,
)
from bugsift.github import rate_limit


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=42, github_login="maintainer", email=None)
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
async def repo_and_app(session, logged_in: User):
    install = Installation(github_installation_id=9001, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1234,
        full_name="acme/web",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    app = FeedbackApp(
        user_id=logged_in.id,
        name="test",
        public_key="pk_test_abc",
        default_repo_id=repo.id,
    )
    session.add(app)
    await session.commit()
    await session.refresh(repo)
    await session.refresh(app)
    return repo, app


def test_adapter_synthesizes_title_and_appendix(session) -> None:
    report = FeedbackReport(
        app_id=1,
        body_text="Save button does nothing on the profile page\nAlso tried refresh.",
        url="https://app.example.com/profile",
        user_agent="Mozilla/5.0",
        app_version="1.4.2",
        console_log="ReferenceError: foo is not defined",
        content_hash="abc",
    )
    state = ingest_feedback.from_feedback_report(
        report=report,
        repo_id=7,
        repo_full_name="acme/web",
        repo_primary_language="Python",
        repo_config={"tone": "professional"},
    )
    assert state.issue_title.startswith("Save button does nothing")
    assert "URL: https://app.example.com/profile" in state.issue_body
    assert "App version: 1.4.2" in state.issue_body
    assert "ReferenceError" in state.issue_body
    assert state.issue_number == 0
    assert state.repo_id == 7


def test_adapter_fallback_title_on_empty_body(session) -> None:
    report = FeedbackReport(app_id=1, body_text="   \n  ", content_hash="x")
    state = ingest_feedback.from_feedback_report(
        report=report,
        repo_id=1,
        repo_full_name="a/b",
        repo_primary_language=None,
        repo_config={},
    )
    assert state.issue_title == "User feedback"


def test_adapter_clips_long_title(session) -> None:
    long_line = "a " * 200  # 400 chars on one line
    report = FeedbackReport(app_id=1, body_text=long_line, content_hash="x")
    state = ingest_feedback.from_feedback_report(
        report=report,
        repo_id=1,
        repo_full_name="a/b",
        repo_primary_language=None,
        repo_config={},
    )
    assert len(state.issue_title) <= 95  # 90 + ellipsis
    assert state.issue_title.endswith("\u2026")


@pytest.mark.asyncio
async def test_ingest_enqueues_triage(
    client, session, repo_and_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app = repo_and_app
    captured: list[int] = []
    monkeypatch.setattr(
        feedback_route,
        "_enqueue_feedback_triage",
        lambda report_id: captured.append(report_id),
    )

    r = client.post(
        "/ingest/feedback",
        json={"text": "crash on save"},
        headers={"X-Bugsift-App-Key": app.public_key},
    )
    assert r.status_code == 202
    assert len(captured) == 1
    assert captured[0] == r.json()["report_id"]


@pytest.mark.asyncio
async def test_cards_list_includes_source_and_counts(
    client, session, repo_and_app, logged_in: User
) -> None:
    repo, app = repo_and_app
    report = FeedbackReport(
        app_id=app.id,
        body_text="crash",
        content_hash="abc",
    )
    session.add(report)
    await session.flush()

    card = TriageCard(
        repo_id=repo.id,
        source="feedback",
        issue_number=None,
        feedback_report_ids_json=[report.id],
        status="pending",
        classification="bug",
    )
    session.add(card)
    await session.commit()
    await session.refresh(report)
    report.card_id = card.id
    await session.commit()

    r = client.get("/cards")
    assert r.status_code == 200
    body = r.json()
    feedback_cards = [c for c in body if c["source"] == "feedback"]
    assert len(feedback_cards) == 1
    assert feedback_cards[0]["feedback_report_count"] == 1
    assert feedback_cards[0]["issue_number"] is None


@pytest.mark.asyncio
async def test_cards_source_filter(
    client, session, repo_and_app, logged_in: User
) -> None:
    repo, app = repo_and_app
    session.add(
        TriageCard(
            repo_id=repo.id,
            source="github",
            issue_number=10,
            status="pending",
            classification="bug",
        )
    )
    session.add(
        TriageCard(
            repo_id=repo.id,
            source="feedback",
            issue_number=None,
            feedback_report_ids_json=[],
            status="pending",
            classification="bug",
        )
    )
    await session.commit()

    r = client.get("/cards?source=feedback")
    assert r.status_code == 200
    assert [c["source"] for c in r.json()] == ["feedback"]


@pytest.mark.asyncio
async def test_card_reports_endpoint(
    client, session, repo_and_app, logged_in: User
) -> None:
    repo, app = repo_and_app
    report = FeedbackReport(
        app_id=app.id,
        body_text="the save page is broken",
        url="https://app.example.com/save",
        app_version="9.9",
        content_hash="x",
    )
    session.add(report)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        source="feedback",
        issue_number=None,
        feedback_report_ids_json=[report.id],
        status="pending",
        classification="bug",
    )
    session.add(card)
    await session.commit()

    r = client.get(f"/cards/{card.id}/reports")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["body_text"] == "the save page is broken"
    assert body[0]["app_version"] == "9.9"


@pytest.mark.asyncio
async def test_card_reports_empty_for_github_card(
    client, session, repo_and_app, logged_in: User
) -> None:
    repo, _ = repo_and_app
    card = TriageCard(
        repo_id=repo.id,
        source="github",
        issue_number=101,
        status="pending",
        classification="bug",
    )
    session.add(card)
    await session.commit()

    r = client.get(f"/cards/{card.id}/reports")
    assert r.status_code == 200
    assert r.json() == []
