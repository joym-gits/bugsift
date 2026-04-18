from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.config import get_settings
from bugsift.db.models import Installation, Repo, RepoConfig
from bugsift.github.rate_limit import allow_installation_event
from bugsift.github.webhooks import verify_signature
from bugsift.workers import triage as triage_jobs

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


def _enqueue_triage(payload: dict[str, Any]) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue("triage", connection=connection)
    queue.enqueue(triage_jobs.process_issue_opened, payload)


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    secret = get_settings().github_app_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GITHUB_APP_WEBHOOK_SECRET is not configured",
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
        return {"status": "queued"}

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
        await _upsert_repos(session, installation, payload.get("repositories") or [])
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
        await _upsert_repos(session, installation, payload.get("repositories_added") or [])
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
) -> None:
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
