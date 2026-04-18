"""Manifest-flow tests.

The first-run operator is anonymous by design — whoever can reach a
fresh deployment IS the operator — so /status, /start, and /callback all
work without a login when no App is configured. The moment a
``github_app_credentials`` row exists, the endpoints flip back: /start
returns 409 and /delete requires auth.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import GithubAppCredentials, User
from bugsift.security import crypto


def test_status_is_public_and_reports_not_configured(client) -> None:
    r = client.get("/github/app/manifest/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False


def test_start_accepts_anonymous_when_no_app_configured(client) -> None:
    r = client.post(
        "/github/app/manifest/start",
        json={"webhook_url": "https://smee.io/abc123"},
    )
    assert r.status_code == 200
    body = r.json()
    # New JSON contract: frontend builds its own form from these fields.
    assert "github.com/settings/apps/new" in body["github_url"]
    assert body["state"]
    assert body["manifest"]["hook_attributes"]["url"] == "https://smee.io/abc123"
    assert "callback_urls" in body["manifest"]


def test_start_requires_valid_webhook_url(client) -> None:
    r = client.post("/github/app/manifest/start", json={"webhook_url": "not a url"})
    assert r.status_code == 422  # pydantic rejects it


@pytest_asyncio.fixture
async def configured_app(session) -> GithubAppCredentials:
    row = GithubAppCredentials(
        id=1,
        github_app_id=12345,
        slug="bugsift-test",
        name="bugsift-test",
        owner_login="octo",
        html_url="https://github.com/apps/bugsift-test",
        client_id="Iv23test",
        client_secret_encrypted=crypto.encrypt("secret"),
        webhook_secret_encrypted=crypto.encrypt("whsecret"),
        private_key_pem_encrypted=crypto.encrypt("-----BEGIN KEY-----"),
    )
    session.add(row)
    await session.commit()
    yield row
    # Explicit cleanup because SQLite in-memory is session-scoped.
    from bugsift.github import config as app_config

    app_config.clear_cache()


def test_status_reports_configured_when_app_exists(client, configured_app) -> None:
    r = client.get("/github/app/manifest/status")
    body = r.json()
    assert body["configured"] is True
    assert body["name"] == "bugsift-test"


def test_start_409_when_app_already_configured(client, configured_app) -> None:
    r = client.post(
        "/github/app/manifest/start",
        json={"webhook_url": "https://smee.io/new"},
    )
    assert r.status_code == 409
    assert "already registered" in r.json()["detail"].lower()


def test_delete_still_requires_auth(client, configured_app) -> None:
    r = client.delete("/github/app/manifest")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_wipes_row_when_authed(client, session, configured_app) -> None:
    user = User(github_id=42, github_login="op", email=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    client.app.dependency_overrides[get_optional_user] = _fake_user
    try:
        r = client.delete("/github/app/manifest")
        assert r.status_code == 204
        # Status flips back to unconfigured.
        assert client.get("/github/app/manifest/status").json()["configured"] is False
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)
        client.app.dependency_overrides.pop(get_optional_user, None)


