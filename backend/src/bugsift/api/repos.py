from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.api.webhooks import _fetch_installation_repos, _upsert_repos
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import Installation, Repo, User
from bugsift.github import app as gh_app
from bugsift.github import config as app_config
from bugsift.workers import enqueue as enqueue_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["repos"])


class RepoResponse(BaseModel):
    id: int
    full_name: str
    default_branch: str
    primary_language: str | None
    indexing_status: str
    indexed_at: datetime | None


@router.get("", response_model=list[RepoResponse])
async def list_repos(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[RepoResponse]:
    stmt = (
        select(Repo)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Installation.user_id == user.id)
        .order_by(Repo.full_name.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        RepoResponse(
            id=r.id,
            full_name=r.full_name,
            default_branch=r.default_branch,
            primary_language=r.primary_language,
            indexing_status=r.indexing_status,
            indexed_at=r.indexed_at,
        )
        for r in rows
    ]


class HydrateResponse(BaseModel):
    added: int
    skipped: int
    installations: int


@router.post("/hydrate", response_model=HydrateResponse)
async def hydrate_repos(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> HydrateResponse:
    """Re-query GitHub for every repo attached to this user's installations
    and add any that aren't already in the DB. Useful when an install
    webhook arrived without its ``repositories`` array populated (a real
    GitHub payload quirk).
    """
    installations = (
        await session.execute(
            select(Installation).where(Installation.user_id == user.id)
        )
    ).scalars().all()

    added = 0
    skipped = 0
    newly_added_repo_ids: list[int] = []
    for install in installations:
        repos_payload = await _fetch_installation_repos(
            session, install.github_installation_id
        )
        if not repos_payload:
            continue
        new_repo_ids = await _upsert_repos(session, install, repos_payload)
        added += len(new_repo_ids)
        skipped += len(repos_payload) - len(new_repo_ids)
        newly_added_repo_ids.extend(new_repo_ids)

    await session.commit()
    # Kick off indexing + backfill for anything newly created. Backfill
    # replays existing open issues through the triage pipeline so the user
    # doesn't need to re-open issues just to see them in the dashboard.
    for repo_id in newly_added_repo_ids:
        enqueue_jobs.enqueue_index_repo(repo_id)
        enqueue_jobs.enqueue_backfill_open_issues(repo_id)
        enqueue_jobs.enqueue_refresh_codeowners(repo_id)
    logger.info(
        "hydrate: user_id=%s installations=%s added=%s",
        user.id,
        len(installations),
        added,
    )
    return HydrateResponse(
        added=added, skipped=skipped, installations=len(installations)
    )


class BranchOut(BaseModel):
    name: str
    is_default: bool


@router.get("/{repo_id}/branches", response_model=list[BranchOut])
async def list_repo_branches(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[BranchOut]:
    """List branches for ``repo_id`` straight from GitHub.

    Keeps the branch picker in the feedback-app form honest — a user
    could have pushed a ``develop`` branch five minutes ago and we don't
    want to store stale state. Paginates GitHub's ``/branches`` endpoint
    with a safety cap; default branch (per the stored Repo row) is
    surfaced as ``is_default`` so the form can preselect it.
    """
    import httpx

    stmt = (
        select(Repo, Installation)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Repo.id == repo_id, Installation.user_id == user.id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repo not found")
    repo, install = row

    cfg = await app_config.load_app_config(session)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App is not configured",
        )

    try:
        token = await gh_app.get_installation_token(
            install.github_installation_id,
            app_id=cfg.app_id,
            private_key_pem=cfg.private_key_pem,
        )
    except Exception as e:
        logger.warning("branches: token mint failed repo_id=%s: %s", repo_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could not mint installation token: {e}",
        ) from e

    names: list[str] = []
    async with httpx.AsyncClient() as client:
        page = 1
        while page <= 10:  # safety cap: 10 pages × 100 = 1000 branches
            response = await client.get(
                f"https://api.github.com/repos/{repo.full_name}/branches",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": 100, "page": page},
                timeout=20.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "branches: GitHub returned %s for %s (page %s)",
                    response.status_code,
                    repo.full_name,
                    page,
                )
                break
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            names.extend(str(b.get("name")) for b in batch if b.get("name"))
            if len(batch) < 100:
                break
            page += 1

    default_branch = (repo.default_branch or "").strip()
    # Preserve API order (GitHub lists alphabetically by default) but
    # float the default branch to the top so the form picks the right
    # initial value.
    sorted_names = sorted(set(names), key=lambda n: (n != default_branch, n))
    return [BranchOut(name=n, is_default=(n == default_branch)) for n in sorted_names]


class BackfillResponse(BaseModel):
    repo_id: int
    queued: bool


class CodeownersRefreshResponse(BaseModel):
    repo_id: int
    queued: bool


@router.post(
    "/{repo_id}/refresh-codeowners", response_model=CodeownersRefreshResponse
)
async def refresh_codeowners_endpoint(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> CodeownersRefreshResponse:
    """Re-pull the repo's CODEOWNERS file into the cache on demand.

    Called by the "Refresh CODEOWNERS" button in the dashboard when
    the operator knows the file changed and doesn't want to wait for
    the next push webhook.
    """
    stmt = (
        select(Repo)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Repo.id == repo_id, Installation.user_id == user.id)
    )
    repo = (await session.execute(stmt)).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    enqueue_jobs.enqueue_refresh_codeowners(repo.id)
    logger.info("codeowners refresh queued repo_id=%s user_id=%s", repo.id, user.id)
    return CodeownersRefreshResponse(repo_id=repo.id, queued=True)


@router.post("/{repo_id}/backfill", response_model=BackfillResponse)
async def backfill_repo(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> BackfillResponse:
    """Manually re-run the existing-issue backfill for one repo.

    Useful when the install webhook raced ahead of the App config being
    saved, or when the user wants to re-pull the open-issue list after
    changing something in the repo.
    """
    stmt = (
        select(Repo)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(Repo.id == repo_id, Installation.user_id == user.id)
    )
    repo = (await session.execute(stmt)).scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="repo not found"
        )
    enqueue_jobs.enqueue_backfill_open_issues(repo.id)
    logger.info("backfill queued for repo_id=%s user_id=%s", repo.id, user.id)
    return BackfillResponse(repo_id=repo.id, queued=True)
