"""Unified lookup of GitHub App credentials.

Credentials come from one of two places:

1. The ``github_app_credentials`` singleton row, populated by the onboarding
   manifest flow — preferred.
2. The ``.env`` settings (`GITHUB_APP_ID`, `GITHUB_APP_CLIENT_ID`, etc.) —
   fallback for operators who prefer to register the App by hand.

Callers always route through :func:`load_app_config` so they never have to
know which source is active. DB-backed credentials are decrypted on each
lookup and cached in-process for a few seconds to avoid round-trips on every
webhook.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.config import get_settings
from bugsift.db.models import GithubAppCredentials
from bugsift.security import crypto

_CACHE_TTL = 30  # seconds
_cache: tuple[float, AppConfig | None] | None = None


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    client_id: str
    client_secret: str
    webhook_secret: str
    private_key_pem: str
    slug: str | None = None
    name: str | None = None
    html_url: str | None = None


async def load_app_config(session: AsyncSession, *, force_refresh: bool = False) -> AppConfig | None:
    """Return the active GitHub App config, or None if nothing's configured."""
    global _cache
    now = time.monotonic()
    if not force_refresh and _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]

    row = (
        await session.execute(
            select(GithubAppCredentials).where(GithubAppCredentials.id == 1)
        )
    ).scalar_one_or_none()
    if row is not None:
        try:
            cfg = AppConfig(
                app_id=str(row.github_app_id),
                client_id=row.client_id,
                client_secret=crypto.decrypt(row.client_secret_encrypted),
                webhook_secret=crypto.decrypt(row.webhook_secret_encrypted),
                private_key_pem=crypto.decrypt(row.private_key_pem_encrypted),
                slug=row.slug,
                name=row.name,
                html_url=row.html_url,
            )
            _cache = (now, cfg)
            return cfg
        except crypto.DecryptionFailed:
            # Encryption key rotated out from under us — fall through to env.
            pass

    # Env fallback. Useful for operators who registered the App manually.
    s = get_settings()
    pem = s.github_app_private_key
    if pem and "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    if not pem and s.github_app_private_key_path:
        try:
            with open(s.github_app_private_key_path) as f:
                pem = f.read()
        except OSError:
            pem = ""
    if not (s.github_app_id and s.github_app_client_id and s.github_app_client_secret and pem):
        _cache = (now, None)
        return None
    cfg = AppConfig(
        app_id=s.github_app_id,
        client_id=s.github_app_client_id,
        client_secret=s.github_app_client_secret,
        webhook_secret=s.github_app_webhook_secret,
        private_key_pem=pem,
    )
    _cache = (now, cfg)
    return cfg


def clear_cache() -> None:
    """Invalidate the in-process config cache. Call after writing creds."""
    global _cache
    _cache = None
