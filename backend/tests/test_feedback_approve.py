"""Slice-4 approve flow for feedback-sourced cards.

Confirms:
- Approving a feedback card calls ``client.create_issue`` with a title
  + body derived from the underlying reports + triage output.
- ``github_issue_number`` lands on the card, status becomes ``posted``.
- Proposed labels are forwarded.
- The issue body formatter produces the expected markdown sections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from types import SimpleNamespace

from bugsift.api import cards as cards_route
from bugsift.api.cards import get_github_client_factory
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TriageCard,
    User,
)
from bugsift.feedback import issue_body
from bugsift.github import rate_limit


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


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


@pytest_asyncio.fixture
async def feedback_card(session, logged_in: User):
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
    app = FeedbackApp(
        user_id=logged_in.id, name="web", public_key="pk_x", default_repo_id=repo.id
    )
    session.add(app)
    await session.flush()
    r1 = FeedbackReport(
        app_id=app.id,
        body_text="Save button does nothing\nsecond line ignored for title",
        url="https://app.example.com/profile",
        app_version="1.4.2",
        content_hash="h1",
    )
    r2 = FeedbackReport(
        app_id=app.id,
        body_text="Save button also broken for me",
        url="https://app.example.com/profile",
        content_hash="h2",
    )
    session.add(r1)
    session.add(r2)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        source="feedback",
        issue_number=None,
        feedback_report_ids_json=[r1.id, r2.id],
        status="pending",
        classification="bug",
        confidence=0.91,
        rationale="Save action has regressed on /profile.",
        draft_comment="Thanks for the report — reproduced and tracking.",
        proposed_labels_json=["bug", "profile"],
        proposed_action="comment_and_label",
        suspected_files_json=[
            {
                "file_path": "app/profile/save.py",
                "line_range": "40-70",
                "rationale": "Handles POST /profile save",
            }
        ],
        reproduction_verdict="reproduced",
        reproduction_log="TypeError: 'NoneType' object is not callable",
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    r1.card_id = card.id
    r2.card_id = card.id
    await session.commit()
    return card, repo, app


def test_issue_body_renders_expected_sections() -> None:
    reports = [
        issue_body.ReportSnippet(
            body_text="First report body",
            url="https://app/a",
            app_version="1.0",
            created_at_iso="2026-04-19T10:00:00+00:00",
        ),
        issue_body.ReportSnippet(
            body_text="Second report body",
            url=None,
            app_version=None,
            created_at_iso="2026-04-19T10:01:00+00:00",
        ),
    ]
    title, body = issue_body.build_issue(
        reports=reports,
        rationale="Looks like a real defect.",
        classification="bug",
        confidence=0.9,
        suspected_files=[
            issue_body.SuspectedFileSnippet(
                file_path="src/foo.py",
                line_range="10-20",
                rationale="handles the crash path",
            )
        ],
        reproduction_verdict="reproduced",
        reproduction_log="TypeError: boom",
    )
    assert title == "First report body"
    assert "## What the user saw" in body
    assert "Report 1" in body and "Report 2" in body
    assert "https://app/a" in body
    assert "## What bugsift found" in body
    assert "`bug`" in body
    assert "Suspected files" in body
    assert "`src/foo.py:10-20`" in body
    assert "Reproduction verdict" in body
    assert "TypeError: boom" in body
    assert "Filed via bugsift from 2 user reports" in body
    # Regression: the old reporter-facing suggestion must be gone.
    assert "Suggested response to the reporter" not in body


def test_issue_body_includes_admin_note_when_provided() -> None:
    reports = [
        issue_body.ReportSnippet(
            body_text="Save button does nothing",
            url="https://app/profile",
            app_version=None,
            created_at_iso="2026-04-19T10:00:00+00:00",
        )
    ]
    _, body = issue_body.build_issue(
        reports=reports,
        rationale=None,
        classification="bug",
        confidence=None,
        suspected_files=[],
        reproduction_verdict=None,
        reproduction_log=None,
        admin_note="Probably the auth middleware — check app/middleware.py",
    )
    assert "## Admin notes" in body
    assert "Probably the auth middleware" in body
    assert body.index("## Admin notes") > body.index("## What the user saw")


def test_issue_body_omits_admin_note_when_blank() -> None:
    reports = [
        issue_body.ReportSnippet(
            body_text="x",
            url=None,
            app_version=None,
            created_at_iso="2026-04-19T10:00:00+00:00",
        )
    ]
    for note in ("", "   ", None):
        _, body = issue_body.build_issue(
            reports=reports,
            rationale=None,
            classification=None,
            confidence=None,
            suspected_files=[],
            reproduction_verdict=None,
            reproduction_log=None,
            admin_note=note,
        )
        assert "## Admin notes" not in body


def test_single_report_omits_report_number_header() -> None:
    reports = [
        issue_body.ReportSnippet(
            body_text="just one",
            url=None,
            app_version=None,
            created_at_iso="2026-04-19T10:00:00+00:00",
        )
    ]
    _, body = issue_body.build_issue(
        reports=reports,
        rationale=None,
        classification=None,
        confidence=None,
        suspected_files=[],
        reproduction_verdict=None,
        reproduction_log=None,
    )
    assert "Report 1" not in body  # lone reports shouldn't feel numbered


@pytest.mark.asyncio
async def test_approve_feedback_card_creates_issue(
    client, feedback_card, monkeypatch: pytest.MonkeyPatch
) -> None:
    card, repo, app = feedback_card

    fake = AsyncMock()
    fake.create_issue = AsyncMock(
        return_value={"number": 4242, "html_url": "https://github.com/demo/widget/issues/4242"}
    )

    captured: dict = {}

    def factory(installation_id: int, **kwargs):
        captured["installation_id"] = installation_id
        captured["kwargs"] = kwargs
        return fake

    async def _fake_cfg(_session):
        return SimpleNamespace(app_id="app-1", private_key_pem="pem")

    monkeypatch.setattr(cards_route.app_config, "load_app_config", _fake_cfg)

    client.app.dependency_overrides[get_github_client_factory] = lambda: factory
    try:
        r = client.post(
            f"/cards/{card.id}/approve",
            json={"admin_note": "probably app/profile/save.py save() handler"},
        )
    finally:
        client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "posted"
    assert body["source"] == "feedback"
    assert body["github_issue_number"] == 4242
    assert body["github_issue_url"].endswith("/issues/4242")

    # The client saw the creation call with the right repo + label set.
    fake.create_issue.assert_awaited_once()
    call = fake.create_issue.await_args
    assert call.args == ("demo/widget",)
    assert call.kwargs["labels"] == ["bug", "profile"]
    assert "Save button does nothing" in call.kwargs["title"]
    assert "## What the user saw" in call.kwargs["body"]
    assert "## What bugsift found" in call.kwargs["body"]
    assert "## Admin notes" in call.kwargs["body"]
    assert "app/profile/save.py" in call.kwargs["body"]
    assert "Filed via bugsift" in call.kwargs["body"]
    assert "Suggested response to the reporter" not in call.kwargs["body"]


@pytest.mark.asyncio
async def test_approve_feedback_card_errors_on_missing_reports(
    client, feedback_card, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    card, repo, app = feedback_card
    card.feedback_report_ids_json = []
    await session.commit()

    fake = AsyncMock()
    fake.create_issue = AsyncMock()

    async def _fake_cfg(_session):
        return SimpleNamespace(app_id="app-1", private_key_pem="pem")

    monkeypatch.setattr(cards_route.app_config, "load_app_config", _fake_cfg)
    client.app.dependency_overrides[get_github_client_factory] = (
        lambda: (lambda installation_id, **kw: fake)
    )
    try:
        r = client.post(f"/cards/{card.id}/approve")
    finally:
        client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 400
    assert "reports to file" in r.json()["detail"]
    fake.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_github_sourced_approve_still_works(
    client, session, logged_in: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the existing github-card approve flow must keep
    posting comments, not opening new issues."""
    install = Installation(github_installation_id=99, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="demo/legacy",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        source="github",
        issue_number=7,
        status="pending",
        classification="bug",
        draft_comment="thanks for the report",
        proposed_action=None,
    )
    session.add(card)
    await session.commit()

    fake = AsyncMock()
    fake.post_issue_comment = AsyncMock(return_value={"id": 1})
    fake.create_issue = AsyncMock()

    async def _fake_cfg(_session):
        return SimpleNamespace(app_id="app-1", private_key_pem="pem")

    monkeypatch.setattr(cards_route.app_config, "load_app_config", _fake_cfg)
    client.app.dependency_overrides[get_github_client_factory] = (
        lambda: (lambda installation_id, **kw: fake)
    )
    try:
        r = client.post(f"/cards/{card.id}/approve")
    finally:
        client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 200
    fake.post_issue_comment.assert_awaited_once()
    fake.create_issue.assert_not_called()
