"""Tests for the ticket destinations feature (Jira v1)."""

from __future__ import annotations

import pytest
import pytest_asyncio
import respx
from fakeredis.aioredis import FakeRedis
from httpx import Response

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TicketDestination,
    TriageCard,
    User,
)
from bugsift.github import rate_limit
from bugsift.security import crypto
from bugsift.tickets.jira import JiraAuthError, JiraClient


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


# --- Jira client (respx-mocked) ---


@pytest.mark.asyncio
async def test_jira_client_validate_ok():
    client = JiraClient(
        site_url="https://acme.atlassian.net",
        user_email="a@b.c",
        api_token="tok",
    )
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "abc"})
        )
        result = await client.validate()
    assert result["accountId"] == "abc"


@pytest.mark.asyncio
async def test_jira_client_validate_401_raises_auth_error():
    client = JiraClient(
        site_url="https://acme.atlassian.net",
        user_email="a@b.c",
        api_token="bad",
    )
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(401, text="unauthorized")
        )
        with pytest.raises(JiraAuthError):
            await client.validate()


@pytest.mark.asyncio
async def test_jira_client_list_projects_returns_parsed_rows():
    client = JiraClient(
        site_url="https://acme.atlassian.net",
        user_email="a@b.c",
        api_token="tok",
    )
    with respx.mock() as mock:
        mock.get(
            "https://acme.atlassian.net/rest/api/3/project/search"
        ).mock(
            return_value=Response(
                200,
                json={
                    "values": [
                        {"id": "10001", "key": "API", "name": "API"},
                        {"id": "10002", "key": "WEB", "name": "Web App"},
                    ]
                },
            )
        )
        projects = await client.list_projects()
    assert [p.key for p in projects] == ["API", "WEB"]


@pytest.mark.asyncio
async def test_jira_client_create_issue_returns_key_and_url():
    client = JiraClient(
        site_url="https://acme.atlassian.net",
        user_email="a@b.c",
        api_token="tok",
    )
    with respx.mock() as mock:
        mock.post("https://acme.atlassian.net/rest/api/2/issue").mock(
            return_value=Response(
                201,
                json={"id": "10010", "key": "API-42", "self": "..."},
            )
        )
        created = await client.create_issue(
            project_key="API",
            issue_type="Bug",
            summary="save button broken",
            description="the body",
            labels=["bug", "needs info"],
        )
    assert created.key == "API-42"
    assert created.url == "https://acme.atlassian.net/browse/API-42"


# --- CRUD API ---


def test_crud_validates_and_persists_jira_destination(client, logged_in: User):
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "u1"})
        )
        r = client.post(
            "/tickets/destinations",
            json={
                "provider": "jira",
                "name": "prod",
                "auth_token": "sekret_token_abc",
                "jira": {
                    "site_url": "https://acme.atlassian.net",
                    "user_email": "alice@acme.com",
                    "default_project_key": "API",
                    "default_issue_type": "Bug",
                },
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "jira"
    assert body["site_url"] == "https://acme.atlassian.net"
    assert body["default_project_key"] == "API"
    # Token masked, never plaintext in the response.
    assert "sekret_token_abc" not in body["token_hint"]


def test_crud_rejects_bad_credentials(client, logged_in: User):
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(401, text="unauthorized")
        )
        r = client.post(
            "/tickets/destinations",
            json={
                "provider": "jira",
                "name": "bad",
                "auth_token": "nope_but_long_enough",
                "jira": {
                    "site_url": "https://acme.atlassian.net",
                    "user_email": "alice@acme.com",
                    "default_project_key": "API",
                },
            },
        )
    assert r.status_code == 400


def test_crud_rejects_non_http_site_url(client, logged_in: User):
    r = client.post(
        "/tickets/destinations",
        json={
            "provider": "jira",
            "name": "bad",
            "auth_token": "plenty_long_token",
            "jira": {
                "site_url": "acme.atlassian.net",  # missing scheme
                "user_email": "alice@acme.com",
                "default_project_key": "API",
            },
        },
    )
    assert r.status_code == 400


def test_list_only_sees_own_destinations(client, logged_in: User):
    # Empty at start.
    assert client.get("/tickets/destinations").json() == []
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "u1"})
        )
        client.post(
            "/tickets/destinations",
            json={
                "provider": "jira",
                "name": "mine",
                "auth_token": "plenty_long_token",
                "jira": {
                    "site_url": "https://acme.atlassian.net",
                    "user_email": "alice@acme.com",
                    "default_project_key": "API",
                },
            },
        )
    rows = client.get("/tickets/destinations").json()
    assert [r["name"] for r in rows] == ["mine"]


def test_delete_destination(client, logged_in: User):
    with respx.mock() as mock:
        mock.get("https://acme.atlassian.net/rest/api/3/myself").mock(
            return_value=Response(200, json={"accountId": "u1"})
        )
        r = client.post(
            "/tickets/destinations",
            json={
                "provider": "jira",
                "name": "tmp",
                "auth_token": "plenty_long_token",
                "jira": {
                    "site_url": "https://acme.atlassian.net",
                    "user_email": "alice@acme.com",
                    "default_project_key": "API",
                },
            },
        )
    dest_id = r.json()["id"]
    assert client.delete(f"/tickets/destinations/{dest_id}").status_code == 204
    assert client.get("/tickets/destinations").json() == []


# --- Approve routing ---


@pytest_asyncio.fixture
async def approve_setup(session, logged_in: User):
    install = Installation(github_installation_id=1, user_id=logged_in.id)
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
    await session.flush()
    destination = TicketDestination(
        user_id=logged_in.id,
        provider="jira",
        name="prod",
        auth_token_encrypted=crypto.encrypt("tok_plaintext"),
        config_json={
            "site_url": "https://acme.atlassian.net",
            "user_email": "alice@acme.com",
            "default_project_key": "API",
            "default_issue_type": "Bug",
        },
    )
    session.add(destination)
    await session.flush()
    app = FeedbackApp(
        user_id=logged_in.id,
        name="web",
        public_key="pk_web",
        default_repo_id=repo.id,
        ticket_destination_id=destination.id,
    )
    session.add(app)
    await session.flush()
    report = FeedbackReport(
        app_id=app.id,
        body_text="Save button broken",
        content_hash="h1",
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
        severity="high",
        confidence=0.91,
        draft_comment="thanks",
        proposed_labels_json=["bug"],
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    await session.refresh(report)
    report.card_id = card.id
    await session.commit()
    return app, repo, destination, card


@pytest.mark.asyncio
async def test_approve_feedback_routes_to_jira(
    client, approve_setup, monkeypatch: pytest.MonkeyPatch
):
    from types import SimpleNamespace

    from bugsift.api import cards as cards_route
    from bugsift.api.cards import get_github_client_factory

    app, repo, destination, card = approve_setup

    async def _fake_cfg(_session):
        return SimpleNamespace(app_id="app-1", private_key_pem="pem")

    monkeypatch.setattr(cards_route.app_config, "load_app_config", _fake_cfg)

    # Inject a github-client factory that must NOT be used in this test —
    # if Jira routing is broken we'd call it and the AsyncMock would fire.
    from unittest.mock import AsyncMock

    github_client = AsyncMock()
    github_client.create_issue = AsyncMock()

    client.app.dependency_overrides[get_github_client_factory] = (
        lambda: (lambda installation_id, **kw: github_client)
    )

    with respx.mock() as mock:
        mock.post("https://acme.atlassian.net/rest/api/2/issue").mock(
            return_value=Response(201, json={"id": "x", "key": "API-7"})
        )
        try:
            r = client.post(f"/cards/{card.id}/approve", json={})
        finally:
            client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "posted"
    assert body["ticket_provider"] == "jira"
    assert body["ticket_key"] == "API-7"
    assert body["ticket_url"] == "https://acme.atlassian.net/browse/API-7"
    # GitHub fallback must not have fired.
    github_client.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_feedback_without_destination_falls_back_to_github(
    client, approve_setup, monkeypatch: pytest.MonkeyPatch, session
):
    """When the feedback app has no ticket_destination_id, approve still
    opens a GitHub issue like before."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bugsift.api import cards as cards_route
    from bugsift.api.cards import get_github_client_factory

    app, repo, destination, card = approve_setup
    app.ticket_destination_id = None
    await session.commit()

    async def _fake_cfg(_session):
        return SimpleNamespace(app_id="app-1", private_key_pem="pem")

    monkeypatch.setattr(cards_route.app_config, "load_app_config", _fake_cfg)

    github_client = AsyncMock()
    github_client.create_issue = AsyncMock(
        return_value={"number": 99, "html_url": "https://github.com/acme/web/issues/99"}
    )
    client.app.dependency_overrides[get_github_client_factory] = (
        lambda: (lambda installation_id, **kw: github_client)
    )
    try:
        r = client.post(f"/cards/{card.id}/approve", json={})
    finally:
        client.app.dependency_overrides.pop(get_github_client_factory, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticket_provider"] == "github"
    assert body["ticket_key"] == "99"
    github_client.create_issue.assert_awaited_once()
