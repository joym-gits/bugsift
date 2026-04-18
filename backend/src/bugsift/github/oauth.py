"""GitHub OAuth client for user login.

We re-use the GitHub App's OAuth credentials (`GITHUB_APP_CLIENT_ID` /
`GITHUB_APP_CLIENT_SECRET`) — a registered GitHub App supports user-to-server
auth via the same flow as a plain OAuth App. This keeps us to one registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from bugsift.config import Settings

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_URL = "https://api.github.com/user/emails"


@dataclass(frozen=True)
class GithubUser:
    id: int
    login: str
    email: str | None


def build_authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.github_app_client_id,
        "redirect_uri": settings.oauth_callback_url,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    settings: Settings, code: str, *, client: httpx.AsyncClient | None = None
) -> str:
    payload = {
        "client_id": settings.github_app_client_id,
        "client_secret": settings.github_app_client_secret,
        "code": code,
        "redirect_uri": settings.oauth_callback_url,
    }
    headers = {"Accept": "application/json"}
    async with _client(client) as c:
        response = await c.post(GITHUB_TOKEN_URL, data=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        body = response.json()
    token = body.get("access_token")
    if not token:
        raise ValueError(f"github did not return an access_token: {body!r}")
    return token


async def fetch_user(token: str, *, client: httpx.AsyncClient | None = None) -> GithubUser:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with _client(client) as c:
        user_resp = await c.get(GITHUB_USER_URL, headers=headers, timeout=10.0)
        user_resp.raise_for_status()
        user = user_resp.json()
        email = user.get("email")
        if not email:
            # Primary email may be hidden; try the /user/emails endpoint.
            emails_resp = await c.get(GITHUB_USER_EMAILS_URL, headers=headers, timeout=10.0)
            if emails_resp.status_code == 200:
                for entry in emails_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        email = entry.get("email")
                        break
    return GithubUser(id=int(user["id"]), login=str(user["login"]), email=email)


def _client(client: httpx.AsyncClient | None) -> httpx.AsyncClient:
    """Return the passed client (caller manages lifecycle) or a new one."""
    if client is not None:
        return _NoCloseClient(client)
    return httpx.AsyncClient()


class _NoCloseClient:
    def __init__(self, inner: httpx.AsyncClient) -> None:
        self._inner = inner

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._inner

    async def __aexit__(self, *exc: object) -> None:
        return None
