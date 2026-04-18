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
    assert r.headers["location"] == "/dashboard"

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
