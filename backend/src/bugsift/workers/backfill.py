"""Backfill existing issues on a newly-installed repo.

When a repo is added (fresh install, installation_repositories.added,
or manual hydrate), pull every open issue from GitHub and enqueue a
normal triage job for each. Each issue rides the same pipeline a real
``issues.opened`` webhook would trigger.

Paginates GitHub's ``/repos/{owner}/{repo}/issues`` endpoint, filters
out pull requests (GitHub lumps PRs into the same endpoint), and
short-circuits if the repo isn't linked to an installation we have a
token for.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from bugsift.db.models import Installation, Repo
from bugsift.db.session import SessionLocal
from bugsift.github import app as gh_app
from bugsift.github import config as app_config
from bugsift.workers import enqueue as enqueue_jobs

logger = logging.getLogger(__name__)

PER_PAGE = 100
MAX_PAGES = 20  # safety cap — 2000 open issues ceiling per call


def backfill_open_issues(repo_id: int) -> None:
    """RQ entrypoint. Sync wrapper around the async implementation."""
    asyncio.run(_backfill_open_issues(repo_id))


async def _backfill_open_issues(repo_id: int) -> None:
    async with SessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if repo is None:
            logger.warning("backfill: repo_id=%s not found", repo_id)
            return
        install = await session.get(Installation, repo.installation_id)
        if install is None:
            logger.warning("backfill: repo_id=%s has no installation", repo_id)
            return
        cfg = await app_config.load_app_config(session)
        if cfg is None:
            logger.warning("backfill: repo_id=%s — no App config", repo_id)
            return

        try:
            token = await gh_app.get_installation_token(
                install.github_installation_id,
                app_id=cfg.app_id,
                private_key_pem=cfg.private_key_pem,
            )
        except Exception as e:
            logger.warning(
                "backfill: token mint failed for install=%s: %s",
                install.github_installation_id,
                e,
            )
            return

        # Snapshot the fields we need — we'll use them after the session closes.
        repo_full_name = repo.full_name
        github_repo_id = repo.github_repo_id
        github_installation_id = install.github_installation_id

    issues = await _list_open_issues(repo_full_name, token)
    logger.info(
        "backfill: repo=%s found %d open issue(s) to triage",
        repo_full_name,
        len(issues),
    )
    if not issues:
        return

    # Each issue gets pushed into the normal triage queue as if it were
    # a fresh issues.opened webhook. The per-installation rate limiter
    # kicks in naturally (and the triage worker no-ops on any issue that
    # already has a card row, so re-running a backfill is idempotent).
    for issue in issues:
        payload = _synthesize_webhook_payload(
            issue=issue,
            repo_full_name=repo_full_name,
            github_repo_id=github_repo_id,
            installation_id=github_installation_id,
        )
        enqueue_jobs.enqueue_triage(payload)


async def _list_open_issues(repo_full_name: str, token: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo_full_name}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, MAX_PAGES + 1):
            response = await client.get(
                url,
                headers=headers,
                params={"state": "open", "per_page": PER_PAGE, "page": page},
                timeout=30.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "backfill: list issues failed for %s: %s %s",
                    repo_full_name,
                    response.status_code,
                    response.text[:200],
                )
                break
            batch = response.json()
            if not isinstance(batch, list):
                break
            # GitHub's /issues endpoint includes PRs; filter them out.
            issues = [item for item in batch if "pull_request" not in item]
            out.extend(issues)
            if len(batch) < PER_PAGE:
                break
    return out


def _synthesize_webhook_payload(
    *,
    issue: dict[str, Any],
    repo_full_name: str,
    github_repo_id: int,
    installation_id: int,
) -> dict[str, Any]:
    """Shape a GitHub API issue object into what ``issues.opened`` sends.

    The triage worker's ``process_issue_opened`` reads ``issue.number``,
    ``repository.id``, ``installation.id`` from the payload. GitHub's
    ``/repos/{owner}/{repo}/issues`` endpoint doesn't include the full
    repository object on every item, so we pass ``github_repo_id``
    through explicitly from the repo row we already have.
    """
    return {
        "action": "opened",
        "issue": {
            "number": issue.get("number"),
            "title": issue.get("title") or "",
            "body": issue.get("body") or "",
            "user": issue.get("user") or {},
            "labels": issue.get("labels") or [],
            "html_url": issue.get("html_url"),
        },
        "repository": {
            "id": github_repo_id,
            "full_name": repo_full_name,
        },
        "installation": {"id": installation_id},
    }
