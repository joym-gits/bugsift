"""Repo analysis worker.

RQ entrypoint kicks off :func:`analyze_repo_for_feedback_app` which
locates the repo behind a feedback app, its owning user's LLM key, runs
the hierarchical analyser, and persists the result on the
``repo_analyses`` row keyed by ``(repo_id, branch)``. Status column
moves pending → running → ready/failed so the dashboard can poll.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from bugsift.analysis.analyzer import analyze_repo
from bugsift.db.models import (
    FeedbackApp,
    Installation,
    Repo,
    RepoAnalysis,
    User,
)
from bugsift.db.session import SessionLocal
from bugsift.llm.factory import get_provider_for_user
from bugsift.security import crypto
from bugsift.workers.triage import DEFAULT_PROVIDER

logger = logging.getLogger(__name__)


def analyze_for_app(feedback_app_id: int) -> None:
    asyncio.run(_analyze_for_app(feedback_app_id))


async def _analyze_for_app(feedback_app_id: int) -> None:
    async with SessionLocal() as session:
        app = await session.get(FeedbackApp, feedback_app_id)
        if app is None:
            logger.warning("analyze_for_app: feedback_app_id=%s not found", feedback_app_id)
            return
        if app.default_repo_id is None:
            logger.warning(
                "analyze_for_app: app_id=%s has no default_repo_id", feedback_app_id
            )
            return
        repo = await session.get(Repo, app.default_repo_id)
        if repo is None:
            logger.warning(
                "analyze_for_app: repo_id=%s missing for app=%s",
                app.default_repo_id,
                feedback_app_id,
            )
            return

        branch = (app.target_branch or repo.default_branch or "main").strip()

        analysis = (
            await session.execute(
                select(RepoAnalysis).where(
                    RepoAnalysis.repo_id == repo.id, RepoAnalysis.branch == branch
                )
            )
        ).scalar_one_or_none()
        if analysis is None:
            analysis = RepoAnalysis(
                repo_id=repo.id, branch=branch, status="running"
            )
            session.add(analysis)
        else:
            analysis.status = "running"
            analysis.error_detail = None
        await session.commit()
        await session.refresh(analysis)

        install = await session.get(Installation, repo.installation_id)
        if install is None or install.user_id is None:
            await _mark_failed(
                session, analysis, "repo has no installation/user linked"
            )
            return

        try:
            user = await _load_user(session, install.user_id)
            provider = await get_provider_for_user(session, user, DEFAULT_PROVIDER)
        except (KeyError, crypto.DecryptionFailed) as e:
            await _mark_failed(
                session, analysis, f"no usable {DEFAULT_PROVIDER} key: {e}"
            )
            return

        overrides = _overrides_as_list(analysis.overrides_json)

        try:
            result = await analyze_repo(
                session,
                repo_id=repo.id,
                provider=provider,
                overrides=overrides,
            )
        except ValueError as e:
            await _mark_failed(session, analysis, str(e))
            return
        except Exception as e:
            logger.exception(
                "analyze_for_app: analyser crashed repo_id=%s branch=%s",
                repo.id,
                branch,
            )
            await _mark_failed(session, analysis, f"analyser crashed: {e}")
            return

        analysis.structured_json = result.structured
        analysis.mermaid_src = result.mermaid_overview
        analysis.status = "ready"
        analysis.error_detail = None
        analysis.generated_at = datetime.now(UTC)
        await session.commit()
        logger.info(
            "analyze_for_app: ready repo_id=%s branch=%s files=%d dirs=%d",
            repo.id,
            branch,
            len(result.files),
            len(result.directories),
        )


async def _mark_failed(session, analysis: RepoAnalysis, detail: str) -> None:
    analysis.status = "failed"
    analysis.error_detail = detail[:2000]
    await session.commit()
    logger.warning(
        "analyze_for_app: FAILED repo_id=%s branch=%s: %s",
        analysis.repo_id,
        analysis.branch,
        detail,
    )


async def _load_user(session, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise KeyError(f"user_id={user_id} not found")
    return user


def _overrides_as_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]
