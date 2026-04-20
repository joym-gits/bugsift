"""Fetch a repo's CODEOWNERS file and cache it on ``repos.codeowners_text``.

GitHub accepts CODEOWNERS in three canonical locations (``CODEOWNERS``,
``.github/CODEOWNERS``, ``docs/CODEOWNERS``); we try them in that order
and take the first one the token can read. The result is persisted as
raw text — no parsing in the worker so we don't lose anything the
parser might later learn to understand.

Called explicitly (on install / hydrate / manual refresh), not on
every triage run — the contents only change when someone merges a
PR touching the file.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from bugsift.db.models import Installation, Repo
from bugsift.db.session import SessionLocal
from bugsift.github import app as gh_app
from bugsift.github import config as app_config

logger = logging.getLogger(__name__)

CANONICAL_PATHS: tuple[str, ...] = (
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
)


def refresh_codeowners(repo_id: int) -> None:
    """RQ entrypoint — sync wrapper."""
    asyncio.run(_refresh_codeowners(repo_id))


async def _refresh_codeowners(repo_id: int) -> None:
    async with SessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if repo is None:
            logger.info("codeowners: repo_id=%s not found; skipping", repo_id)
            return
        install = await session.get(Installation, repo.installation_id)
        if install is None:
            logger.info(
                "codeowners: repo_id=%s has no installation; skipping", repo_id
            )
            return
        cfg = await app_config.load_app_config(session)
        if cfg is None:
            logger.warning(
                "codeowners: repo_id=%s — GitHub App not configured; skipping",
                repo_id,
            )
            return
        try:
            token = await gh_app.get_installation_token(
                install.github_installation_id,
                app_id=cfg.app_id,
                private_key_pem=cfg.private_key_pem,
            )
        except Exception as e:
            logger.warning(
                "codeowners: token mint failed for install=%s: %s",
                install.github_installation_id,
                e,
            )
            return

        text = await _fetch_first_match(repo.full_name, token)
        # Persist even when ``text is None`` so the timestamp advances
        # and we don't re-hit GitHub every card.
        repo.codeowners_text = text
        repo.codeowners_fetched_at = datetime.now(UTC)
        await session.commit()
        if text:
            logger.info(
                "codeowners: repo=%s cached %d bytes", repo.full_name, len(text)
            )
        else:
            logger.info("codeowners: repo=%s has no CODEOWNERS file", repo.full_name)


async def _fetch_first_match(repo_full_name: str, token: str) -> str | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for path in CANONICAL_PATHS:
            url = f"https://api.github.com/repos/{repo_full_name}/contents/{path}"
            try:
                response = await client.get(url, headers=headers, timeout=15.0)
            except httpx.HTTPError as e:
                logger.warning("codeowners fetch error for %s: %s", path, e)
                continue
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                logger.warning(
                    "codeowners: %s returned %s", path, response.status_code
                )
                continue
            raw = response.content
            # Guard against binary files named CODEOWNERS for some reason.
            if not raw or len(raw) > 500 * 1024:
                return None
            return raw.decode("utf-8", errors="replace")
    return None
