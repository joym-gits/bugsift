"""Tests for the feedback ingestion slice.

Covers:
- Widget JS endpoint serves the bundle with correct content-type.
- Creating a feedback app returns a public key + repo binding.
- Listing apps only shows the owning user's apps.
- Ingest requires a valid app key, honours origin allowlist, and writes
  ``feedback_reports`` rows with captured context.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    User,
)
from bugsift.github import rate_limit


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    """The ingest endpoint rate-limits via the same redis client as the
    webhook rate limiter. Swap for fakeredis so tests don't need Redis."""
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
async def owned_repo(session, logged_in: User):
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
    await session.commit()
    await session.refresh(repo)
    return repo


def test_widget_js_served(client) -> None:
    r = client.get("/widget.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "X-Bugsift-App-Key" in r.text
    assert "bugsift" in r.text


def test_widget_cors_preflight(client) -> None:
    r = client.options(
        "/ingest/feedback",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "X-Bugsift-App-Key" in r.headers["access-control-allow-headers"]


def test_create_feedback_app(client, logged_in: User, owned_repo: Repo) -> None:
    r = client.post(
        "/feedback/apps",
        json={"name": "Acme Web", "default_repo_id": owned_repo.id},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Acme Web"
    assert body["public_key"].startswith("pk_")
    assert body["default_repo_full_name"] == "acme/web"
    assert body["report_count"] == 0


def test_cannot_bind_repo_user_does_not_own(
    client, logged_in: User, session, owned_repo: Repo
) -> None:
    # Another user owns a different repo.
    stranger = User(github_id=99, github_login="stranger", email=None)
    session.add(stranger)
    import asyncio

    async def _setup():
        stranger_install = Installation(github_installation_id=555, user_id=99)
        session.add(stranger_install)
        await session.flush()
        stranger_repo = Repo(
            installation_id=stranger_install.id,
            github_repo_id=555,
            full_name="stranger/repo",
            default_branch="main",
            indexing_status="pending",
        )
        session.add(stranger_repo)
        await session.commit()
        return stranger_repo.id

    stranger_repo_id = asyncio.get_event_loop().run_until_complete(_setup())
    r = client.post(
        "/feedback/apps",
        json={"name": "bad", "default_repo_id": stranger_repo_id},
    )
    assert r.status_code == 400


def test_list_only_your_apps(client, logged_in: User, owned_repo: Repo, session) -> None:
    client.post("/feedback/apps", json={"name": "Mine", "default_repo_id": owned_repo.id})
    r = client.get("/feedback/apps")
    assert r.status_code == 200
    names = [a["name"] for a in r.json()]
    assert names == ["Mine"]


def test_ingest_rejects_missing_key(client) -> None:
    r = client.post("/ingest/feedback", json={"text": "anything"})
    assert r.status_code == 401


def test_ingest_rejects_invalid_key(client) -> None:
    r = client.post(
        "/ingest/feedback",
        json={"text": "anything"},
        headers={"X-Bugsift-App-Key": "pk_does_not_exist"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingest_writes_report(
    client, logged_in: User, owned_repo: Repo, session
) -> None:
    create = client.post(
        "/feedback/apps", json={"name": "web", "default_repo_id": owned_repo.id}
    )
    public_key = create.json()["public_key"]

    r = client.post(
        "/ingest/feedback",
        json={
            "text": "clicked Save and saw a white screen",
            "url": "https://app.example.com/profile",
            "user_agent": "Mozilla/5.0 ...",
            "app_version": "1.4.2",
            "console_log": "ReferenceError: foo is not defined",
            "reporter_id": "user@example.com",
        },
        headers={"X-Bugsift-App-Key": public_key},
    )
    assert r.status_code == 202, r.text
    report_id = r.json()["report_id"]

    row = (
        await session.execute(select(FeedbackReport).where(FeedbackReport.id == report_id))
    ).scalar_one()
    assert row.body_text == "clicked Save and saw a white screen"
    assert row.app_version == "1.4.2"
    assert row.reporter_hash and len(row.reporter_hash) == 64  # sha256 hex
    assert row.reporter_hash != "user@example.com"  # never plaintext
    assert row.content_hash and len(row.content_hash) == 64


@pytest.mark.asyncio
async def test_ingest_origin_allowlist(
    client, logged_in: User, owned_repo: Repo, session
) -> None:
    create = client.post(
        "/feedback/apps",
        json={
            "name": "locked",
            "default_repo_id": owned_repo.id,
            "allowed_origins": ["https://app.example.com"],
        },
    )
    public_key = create.json()["public_key"]

    # Wrong origin → 403.
    r = client.post(
        "/ingest/feedback",
        json={"text": "hi"},
        headers={
            "X-Bugsift-App-Key": public_key,
            "Origin": "https://evil.example.com",
        },
    )
    assert r.status_code == 403

    # Correct origin → accepted.
    r = client.post(
        "/ingest/feedback",
        json={"text": "hi"},
        headers={
            "X-Bugsift-App-Key": public_key,
            "Origin": "https://app.example.com",
        },
    )
    assert r.status_code == 202


def test_delete_feedback_app(client, logged_in: User, owned_repo: Repo) -> None:
    create = client.post("/feedback/apps", json={"name": "temp"})
    app_id = create.json()["id"]
    r = client.delete(f"/feedback/apps/{app_id}")
    assert r.status_code == 204
    assert client.get("/feedback/apps").json() == []
