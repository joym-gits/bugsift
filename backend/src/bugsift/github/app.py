"""GitHub App authentication.

Two tiers:

- **App JWT** — signed with the App's private RSA key; used to mint installation
  tokens and fetch metadata about the App itself.
- **Installation token** — short-lived (~1 hour), scoped to a single installation,
  used for every repo-level call (posting comments, reading files, applying
  labels). Cached in memory with a safety margin to avoid thrashing.

Phase 3 doesn't make outbound calls yet, but the helpers live here so the
later phases that do (comment posting in phase 5, indexing in phase 6) have a
stable entry point.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from bugsift.config import Settings, get_settings

GITHUB_API_URL = "https://api.github.com"


class AppConfigError(RuntimeError):
    """Raised when the GitHub App credentials are incomplete."""


@dataclass
class InstallationToken:
    token: str
    expires_at: int  # epoch seconds


def _load_private_key(settings: Settings) -> str:
    inline = settings.github_app_private_key.strip() if settings.github_app_private_key else ""
    if inline:
        # Allow either raw PEM or a single-line version with literal "\n" escapes.
        return inline.replace("\\n", "\n")
    path = settings.github_app_private_key_path.strip() if settings.github_app_private_key_path else ""
    if path:
        return Path(path).read_text()
    raise AppConfigError(
        "GitHub App private key is not configured. Set GITHUB_APP_PRIVATE_KEY or "
        "GITHUB_APP_PRIVATE_KEY_PATH."
    )


def generate_jwt(settings: Settings | None = None, *, now: int | None = None) -> str:
    """Mint a 10-minute App-level JWT. Clock-skew-safe (issued 60s in the past)."""
    settings = settings or get_settings()
    if not settings.github_app_id:
        raise AppConfigError("GITHUB_APP_ID is not set")
    current = int(time.time()) if now is None else now
    payload = {
        "iat": current - 60,
        "exp": current + 9 * 60,
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, _load_private_key(settings), algorithm="RS256")


_installation_token_cache: dict[int, InstallationToken] = {}
_SAFETY_MARGIN = 120  # refresh 2 minutes before actual expiry


async def get_installation_token(
    installation_id: int,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    settings = settings or get_settings()
    now = int(time.time())
    cached = _installation_token_cache.get(installation_id)
    if cached and cached.expires_at - _SAFETY_MARGIN > now:
        return cached.token

    jwt_token = generate_jwt(settings, now=now)
    url = f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    close_after = client is None
    c = client or httpx.AsyncClient()
    try:
        response = await c.post(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        body = response.json()
    finally:
        if close_after:
            await c.aclose()

    token = body["token"]
    # body["expires_at"] looks like "2026-04-18T09:00:00Z" — we parse to epoch.
    expires_at_str = body["expires_at"]
    expires_at = int(time.mktime(time.strptime(expires_at_str, "%Y-%m-%dT%H:%M:%SZ")))
    _installation_token_cache[installation_id] = InstallationToken(token, expires_at)
    return token


def clear_installation_token_cache(installation_id: int | None = None) -> None:
    """Invalidate cached tokens. Useful in tests and on 401 responses."""
    if installation_id is None:
        _installation_token_cache.clear()
    else:
        _installation_token_cache.pop(installation_id, None)
