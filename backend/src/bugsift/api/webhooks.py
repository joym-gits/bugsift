from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.config import get_settings
from bugsift.db.models import Installation, Repo, RepoConfig
from bugsift.github import config as app_config
from bugsift.github.rate_limit import allow_installation_event
from bugsift.github.webhooks import verify_signature
from bugsift.workers import enqueue as enqueue_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

DEFAULT_ENABLED_STEPS = {"classify": True, "dedup": True, "retrieval": True, "reproduction": True}
DEFAULT_AUTO_ACTIONS = {
    "duplicate": True,
    "needs_info": True,
    "bug": False,
    "feature_request": False,
}
DEFAULT_LABEL_MAP = {
    "bug": "bug",
    "needs_info": "needs-info",
    "duplicate": "duplicate",
    "good_first_issue": "good-first-issue",
    "feature_request": "enhancement",
}
DEFAULT_REPRO_LANGUAGES = {"languages": ["python", "node"]}


# Thin aliases so the webhook tests can monkey-patch a single symbol and
# the routes stay readable.
_enqueue_triage = enqueue_jobs.enqueue_triage
_enqueue_index_repo = enqueue_jobs.enqueue_index_repo
_enqueue_index_repo_delta = enqueue_jobs.enqueue_index_repo_delta
_enqueue_embed_issue = enqueue_jobs.enqueue_embed_issue


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    cfg = await app_config.load_app_config(session)
    secret = cfg.webhook_secret if cfg else get_settings().github_app_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App webhook secret not configured",
        )
    body = await request.body()
    if not verify_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json") from e

    event = (x_github_event or "").lower()
    action = payload.get("action")

    if event == "ping":
        return {"status": "pong"}

    if event == "installation":
        await _handle_installation(session, action, payload)
        return {"status": "ok"}

    if event == "installation_repositories":
        await _handle_installation_repositories(session, action, payload)
        return {"status": "ok"}

    if event == "issues" and action == "opened":
        installation_id = (payload.get("installation") or {}).get("id")
        if installation_id is not None:
            allowed = await allow_installation_event(int(installation_id))
            if not allowed:
                return {"status": "rate_limited"}
        _enqueue_triage(payload)
        await _enqueue_embed_issue_for_payload(session, payload)
        return {"status": "queued"}

    if event == "issues" and action == "edited":
        await _enqueue_embed_issue_for_payload(session, payload)
        return {"status": "queued"}

    if event == "push":
        await _handle_push(session, payload)
        return {"status": "ok"}

    logger.debug("ignoring webhook event=%s action=%s", event, action)
    return {"status": "ignored"}


async def _handle_installation(
    session: AsyncSession, action: str | None, payload: dict[str, Any]
) -> None:
    install_payload = payload.get("installation") or {}
    github_installation_id = install_payload.get("id")
    if not github_installation_id:
        return
    installation = (
        await session.execute(
            select(Installation).where(Installation.github_installation_id == github_installation_id)
        )
    ).scalar_one_or_none()

    if action == "created":
        # We may not know the user yet — the authenticated install callback
        # (see api/github.py) is what links this row to a user. If we already
        # have an installation from the callback, keep its user_id.
        if installation is None:
            # user_id stays null here — the authenticated install callback
            # links it to the user who clicked Install on GitHub.
            installation = Installation(github_installation_id=github_installation_id)
            session.add(installation)
            await session.flush()
        new_repos = await _upsert_repos(session, installation, payload.get("repositories") or [])
        await session.commit()
        for repo_id in new_repos:
            _enqueue_index_repo(repo_id)
        return
    elif action == "deleted":
        if installation is not None:
            await session.delete(installation)
    elif action in {"suspend", "unsuspend"}:
        if installation is not None:
            from datetime import UTC, datetime

            installation.suspended_at = datetime.now(UTC) if action == "suspend" else None
    await session.commit()


async def _handle_installation_repositories(
    session: AsyncSession, action: str | None, payload: dict[str, Any]
) -> None:
    install_payload = payload.get("installation") or {}
    github_installation_id = install_payload.get("id")
    installation = (
        await session.execute(
            select(Installation).where(Installation.github_installation_id == github_installation_id)
        )
    ).scalar_one_or_none()
    if installation is None:
        logger.warning("installation_repositories for unknown installation=%s", github_installation_id)
        return

    if action == "added":
        new_repos = await _upsert_repos(session, installation, payload.get("repositories_added") or [])
        await session.commit()
        for repo_id in new_repos:
            _enqueue_index_repo(repo_id)
        return
    elif action == "removed":
        removed_ids = [r.get("id") for r in (payload.get("repositories_removed") or []) if r.get("id")]
        if removed_ids:
            await session.execute(
                Repo.__table__.delete().where(
                    Repo.installation_id == installation.id, Repo.github_repo_id.in_(removed_ids)
                )
            )
    await session.commit()


async def _upsert_repos(
    session: AsyncSession, installation: Installation, repositories: list[dict[str, Any]]
) -> list[int]:
    """Insert or update repos under ``installation``. Returns ids of newly
    created repos so the caller can enqueue an initial index for them."""
    new_repo_ids: list[int] = []
    for repo_payload in repositories:
        github_repo_id = repo_payload.get("id")
        if not github_repo_id:
            continue
        existing = (
            await session.execute(select(Repo).where(Repo.github_repo_id == github_repo_id))
        ).scalar_one_or_none()
        if existing is not None:
            existing.installation_id = installation.id
            existing.full_name = repo_payload.get("full_name") or existing.full_name
            continue
        repo = Repo(
            installation_id=installation.id,
            github_repo_id=github_repo_id,
            full_name=repo_payload.get("full_name") or "",
            default_branch=repo_payload.get("default_branch") or "main",
            primary_language=repo_payload.get("language"),
            indexing_status="pending",
        )
        session.add(repo)
        await session.flush()
        session.add(
            RepoConfig(
                repo_id=repo.id,
                enabled_steps_json=DEFAULT_ENABLED_STEPS,
                auto_actions_json=DEFAULT_AUTO_ACTIONS,
                label_map_json=DEFAULT_LABEL_MAP,
                reproduce_languages_json=DEFAULT_REPRO_LANGUAGES,
            )
        )
        new_repo_ids.append(repo.id)
    return new_repo_ids


async def _handle_push(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Only process push events against the repo's default branch; compute
    the union of added/modified/removed paths across all commits in the push."""
    ref = payload.get("ref") or ""
    repo_payload = payload.get("repository") or {}
    github_repo_id = repo_payload.get("id")
    default_branch = repo_payload.get("default_branch") or "main"
    if ref != f"refs/heads/{default_branch}" or not github_repo_id:
        return

    repo = (
        await session.execute(select(Repo).where(Repo.github_repo_id == github_repo_id))
    ).scalar_one_or_none()
    if repo is None:
        return

    added: set[str] = set()
    modified: set[str] = set()
    removed: set[str] = set()
    for commit in payload.get("commits") or []:
        added.update(commit.get("added") or [])
        modified.update(commit.get("modified") or [])
        removed.update(commit.get("removed") or [])
    # A path removed in one commit and re-added in another should count as modified.
    overlap = (added | modified) & removed
    removed -= overlap

    if not (added or modified or removed):
        return
    _enqueue_index_repo_delta(
        repo.id, added=sorted(added), modified=sorted(modified), removed=sorted(removed)
    )


async def _enqueue_embed_issue_for_payload(
    session: AsyncSession, payload: dict[str, Any]
) -> None:
    issue = payload.get("issue") or {}
    repo_payload = payload.get("repository") or {}
    github_repo_id = repo_payload.get("id")
    issue_number = issue.get("number")
    if not github_repo_id or not issue_number:
        return
    repo = (
        await session.execute(select(Repo).where(Repo.github_repo_id == github_repo_id))
    ).scalar_one_or_none()
    if repo is None:
        return
    _enqueue_embed_issue(
        repo.id,
        int(issue_number),
        str(issue.get("title") or ""),
        str(issue.get("body") or ""),
    )
