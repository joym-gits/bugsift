from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.config import get_settings
from bugsift.db.models import Installation, PushEvent, Repo, RepoConfig
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
_enqueue_backfill_open_issues = enqueue_jobs.enqueue_backfill_open_issues


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
    # Log every incoming event + action + final outcome so diagnosing
    # "my issue didn't show up" is one `docker compose logs` away.
    outcome = "ignored"
    try:
        if event == "ping":
            outcome = "pong"
            return {"status": "pong"}

        if event == "installation":
            await _handle_installation(session, action, payload)
            outcome = "ok"
            return {"status": "ok"}

        if event == "installation_repositories":
            await _handle_installation_repositories(session, action, payload)
            outcome = "ok"
            return {"status": "ok"}

        if event == "issues" and action == "opened":
            installation_id = (payload.get("installation") or {}).get("id")
            if installation_id is not None:
                allowed = await allow_installation_event(int(installation_id))
                if not allowed:
                    outcome = "rate_limited"
                    return {"status": "rate_limited"}
            _enqueue_triage(payload)
            await _enqueue_embed_issue_for_payload(session, payload)
            outcome = "queued"
            return {"status": "queued"}

        if event == "issues" and action == "edited":
            await _enqueue_embed_issue_for_payload(session, payload)
            outcome = "queued"
            return {"status": "queued"}

        if event == "push":
            await _handle_push(session, payload)
            outcome = "ok"
            return {"status": "ok"}

        return {"status": "ignored"}
    finally:
        repo_full_name = (payload.get("repository") or {}).get("full_name")
        issue_number = (payload.get("issue") or {}).get("number")
        logger.info(
            "webhook event=%s action=%s outcome=%s repo=%s issue=%s",
            event,
            action,
            outcome,
            repo_full_name,
            issue_number,
        )


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
        repos_in_payload = payload.get("repositories") or []
        # Some install flows (e.g. "select repositories" with an empty
        # current selection, or re-delivered events) ship installation.created
        # without the repositories array populated. In that case the App /
        # installation_repositories.added event may or may not follow — not
        # enough to rely on. Ask GitHub directly so we don't sit empty-handed.
        if not repos_in_payload:
            repos_in_payload = await _fetch_installation_repos(session, github_installation_id)
        new_repos = await _upsert_repos(session, installation, repos_in_payload)
        await session.commit()
        for repo_id in new_repos:
            _enqueue_index_repo(repo_id)
            # Every brand-new repo gets a backfill pass so existing open
            # issues land in the queue, not just issues opened after we
            # were installed.
            _enqueue_backfill_open_issues(repo_id)
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
            _enqueue_backfill_open_issues(repo_id)
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


async def _fetch_installation_repos(
    session: AsyncSession, github_installation_id: int
) -> list[dict[str, Any]]:
    """Pull the live repository list for an installation from GitHub.

    Used as a fallback when the webhook payload arrives without a
    ``repositories`` array, and exposed through a hydrate endpoint for
    manual recovery.
    """
    import httpx

    from bugsift.github import app as gh_app

    cfg = await app_config.load_app_config(session)
    if cfg is None:
        logger.warning(
            "_fetch_installation_repos: no App config; cannot hydrate installation=%s",
            github_installation_id,
        )
        return []
    try:
        token = await gh_app.get_installation_token(
            github_installation_id,
            app_id=cfg.app_id,
            private_key_pem=cfg.private_key_pem,
        )
    except Exception as e:
        logger.warning(
            "_fetch_installation_repos: token mint failed for %s: %s",
            github_installation_id,
            e,
        )
        return []
    out: list[dict[str, Any]] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                "https://api.github.com/installation/repositories",
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
                    "_fetch_installation_repos: list failed %s for installation=%s",
                    response.status_code,
                    github_installation_id,
                )
                break
            batch = response.json().get("repositories") or []
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    return out


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
            # Refresh mutable metadata on every hydrate so values that were
            # empty at install time (e.g. ``language`` before any commit)
            # catch up automatically.
            payload_lang = repo_payload.get("language")
            if payload_lang:
                existing.primary_language = payload_lang
            payload_default = repo_payload.get("default_branch")
            if payload_default:
                existing.default_branch = payload_default
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
    the union of added/modified/removed paths across all commits in the push,
    and persist a row per commit for the regression correlator."""
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

    await _persist_push_events(session, repo=repo, payload=payload, ref=ref)
    # Commit so the PushEvent rows are visible to subsequent triage
    # jobs (which run out-of-process and would otherwise not see our
    # uncommitted rows). Indexing delta jobs also read from the DB via
    # their own sessions, so ordering matters here.
    await session.commit()

    if not (added or modified or removed):
        return
    _enqueue_index_repo_delta(
        repo.id, added=sorted(added), modified=sorted(modified), removed=sorted(removed)
    )


_PR_IN_MESSAGE_RE = re.compile(r"\(#(\d+)\)|Merge pull request #(\d+)")


async def _persist_push_events(
    session: AsyncSession, *, repo: Repo, payload: dict[str, Any], ref: str
) -> None:
    """Write one :class:`PushEvent` row per commit in the push.

    The regression correlator reads these rows to overlap a card's
    suspected files against what recently landed. We parse the PR number
    out of the commit message heuristically (Merge / squash commits carry
    ``(#NNN)``) — good enough to surface a link without a second API call.
    """
    commits = payload.get("commits") or []
    if not commits:
        return
    pusher = payload.get("pusher") or {}
    for commit in commits:
        sha = str(commit.get("id") or "").strip()
        if not sha:
            continue
        # INSERT ON CONFLICT DO NOTHING — idempotent under webhook replays.
        existing = (
            await session.execute(
                select(PushEvent).where(
                    PushEvent.repo_id == repo.id, PushEvent.commit_sha == sha
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        raw_message = str(commit.get("message") or "").strip()
        first_line = raw_message.split("\n", 1)[0][:500]
        touched = sorted(
            set(commit.get("added") or [])
            | set(commit.get("modified") or [])
        )
        pushed_at = _parse_commit_timestamp(
            commit.get("timestamp") or payload.get("head_commit", {}).get("timestamp")
        )
        author = commit.get("author") or {}
        pr_number = _parse_pr_number(raw_message)
        session.add(
            PushEvent(
                repo_id=repo.id,
                commit_sha=sha,
                message_first_line=first_line,
                author_name=str(author.get("name") or "") or None,
                author_login=str(
                    author.get("username") or pusher.get("name") or ""
                )
                or None,
                pushed_at=pushed_at,
                ref=ref,
                touched_paths_json=touched or None,
                pr_number=pr_number,
            )
        )


def _parse_commit_timestamp(value: Any) -> datetime:
    from datetime import UTC, datetime as _dt

    if isinstance(value, str) and value:
        try:
            return _dt.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return _dt.now(UTC)


def _parse_pr_number(message: str) -> int | None:
    match = _PR_IN_MESSAGE_RE.search(message or "")
    if match is None:
        return None
    for grp in match.groups():
        if grp:
            try:
                return int(grp)
            except ValueError:
                return None
    return None


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
