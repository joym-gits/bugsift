from __future__ import annotations

import pytest
import respx
from httpx import Response

from bugsift.config import get_settings


def test_me_returns_null_when_not_logged_in(client) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json() is None


def test_github_start_503_when_oauth_not_configured(client) -> None:
    r = client.get("/auth/github/start", follow_redirects=False)
    assert r.status_code == 503


def test_github_start_redirects_when_configured(client, monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(s, "github_app_client_secret", "test-secret")
    r = client.get("/auth/github/start", follow_redirects=False)
    assert r.status_code == 307
    assert "github.com/login/oauth/authorize" in r.headers["location"]
    assert "client_id=test-client-id" in r.headers["location"]


def test_logout_requires_login(client) -> None:
    r = client.post("/auth/logout")
    assert r.status_code == 401


@respx.mock
def test_oauth_callback_creates_user_and_sets_session(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(s, "github_app_client_secret", "test-secret")

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_fake", "token_type": "bearer"})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"id": 42, "login": "octocat", "email": "o@example.com"})
    )

    # Prime session state via /start so the callback's state check passes.
    start = client.get("/auth/github/start", follow_redirects=False)
    assert start.status_code == 307
    state = start.headers["location"].split("state=")[-1]

    r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303
    # First-time user: no installation / no key → wizard.
    assert r.headers["location"] == "/onboarding"

    me = client.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["github_login"] == "octocat"
    assert body["github_id"] == 42
    assert body["email"] == "o@example.com"


def test_oauth_callback_rejects_state_mismatch(client, monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(s, "github_app_client_secret", "test-secret")

    r = client.get("/auth/github/callback?code=abc&state=not-the-right-state", follow_redirects=False)
    assert r.status_code == 400


@respx.mock
def test_oauth_callback_returning_user_goes_to_dashboard(
    client, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User who's already installed the App and saved an LLM key should
    skip the wizard and land on the dashboard on subsequent logins.
    """
    import asyncio
    from decimal import Decimal

    from bugsift.db.models import Installation, User, UserApiKey
    from bugsift.security import crypto

    async def _seed() -> None:
        user = User(github_id=42, github_login="octocat", email="o@example.com")
        session.add(user)
        await session.flush()
        session.add(Installation(github_installation_id=9001, user_id=user.id))
        session.add(
            UserApiKey(
                user_id=user.id,
                provider="anthropic",
                encrypted_key=crypto.encrypt("sk-ant-existing"),
                masked_hint="sk-••••••ting",
            )
        )
        await session.commit()

    asyncio.get_event_loop().run_until_complete(_seed())
    _ = Decimal  # silence unused

    s = get_settings()
    monkeypatch.setattr(s, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(s, "github_app_client_secret", "test-secret")

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_fake", "token_type": "bearer"})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"id": 42, "login": "octocat", "email": "o@example.com"})
    )

    start = client.get("/auth/github/start", follow_redirects=False)
    state = start.headers["location"].split("state=")[-1]
    r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
