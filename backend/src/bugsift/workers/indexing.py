"""Indexing worker jobs.

Three entry points RQ calls:

- :func:`index_repo` — first install or manual re-index. Full tarball.
- :func:`index_repo_delta` — push webhook. Touch only changed files.
- :func:`embed_issue` — issues.opened / issues.edited. Upsert the issue's
  embedding for dedup search.

Each is a thin sync wrapper around the async implementation so RQ stays
happy. All three are idempotent — safe to re-enqueue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import Installation, IssueEmbedding, Repo
from bugsift.db.session import SessionLocal
from bugsift.github import config as app_config
from bugsift.retrieval.embedding import (
    EmbeddingUnavailable,
    get_embedder_for_repo,
    model_slug,
)
from bugsift.retrieval.indexer import RepoIndexer, _dim_column

logger = logging.getLogger(__name__)


# ---------- public sync entry points ----------


def index_repo(repo_id: int) -> None:
    asyncio.run(_index_repo(repo_id))


def index_repo_delta(
    repo_id: int, *, added: list[str], modified: list[str], removed: list[str]
) -> None:
    asyncio.run(_index_repo_delta(repo_id, added=added, modified=modified, removed=removed))


def embed_issue(
    repo_id: int, issue_number: int, title: str, body: str
) -> None:
    asyncio.run(_embed_issue(repo_id, issue_number, title, body))


# ---------- async implementations ----------


async def _with_embedder(session: AsyncSession, repo: Repo):
    install = await session.get(Installation, repo.installation_id)
    if install is None or install.user_id is None:
        raise EmbeddingUnavailable("installation has no linked user")
    return await get_embedder_for_repo(session, repo, install.user_id)


async def _index_repo(repo_id: int) -> None:
    async with SessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if repo is None:
            logger.warning("index_repo: repo_id=%s not found", repo_id)
            return
        install = await session.get(Installation, repo.installation_id)
        cfg = await app_config.load_app_config(session)
        if cfg is None:
            logger.warning(
                "index_repo: %s — GitHub App not configured yet; leaving repo pending",
                repo.full_name,
            )
            return
        try:
            provider, choice = await _with_embedder(session, repo)
        except EmbeddingUnavailable as e:
            repo.indexing_status = "skipped_no_embedder"
            await session.commit()
            logger.warning("index_repo: %s — %s", repo.full_name, e)
            return

        indexer = RepoIndexer(
            session,
            provider,
            choice,
            app_id=cfg.app_id,
            private_key_pem=cfg.private_key_pem,
        )
        written = await indexer.full_index(repo, install.github_installation_id)
        logger.info(
            "index_repo %s: wrote %d chunks using %s",
            repo.full_name,
            written,
            model_slug(choice),
        )


async def _index_repo_delta(
    repo_id: int, *, added: list[str], modified: list[str], removed: list[str]
) -> None:
    async with SessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if repo is None:
            return
        install = await session.get(Installation, repo.installation_id)
        cfg = await app_config.load_app_config(session)
        if cfg is None:
            logger.warning(
                "index_repo_delta: %s — GitHub App not configured; skipping",
                repo.full_name,
            )
            return
        try:
            provider, choice = await _with_embedder(session, repo)
        except EmbeddingUnavailable as e:
            logger.warning("index_repo_delta: %s — %s; skipping", repo.full_name, e)
            return
        indexer = RepoIndexer(
            session,
            provider,
            choice,
            app_id=cfg.app_id,
            private_key_pem=cfg.private_key_pem,
        )
        written = await indexer.delta_index(
            repo,
            install.github_installation_id,
            added=added,
            modified=modified,
            removed=removed,
        )
        logger.info(
            "index_repo_delta %s: +%d (added+modified=%d, removed=%d)",
            repo.full_name,
            written,
            len(added) + len(modified),
            len(removed),
        )


async def _embed_issue(repo_id: int, issue_number: int, title: str, body: str) -> None:
    async with SessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if repo is None:
            return
        try:
            provider, choice = await _with_embedder(session, repo)
        except EmbeddingUnavailable as e:
            logger.info(
                "embed_issue: %s#%s skipped — %s", repo.full_name, issue_number, e
            )
            return

        # Pin the repo to this dim if it's the first embedding we see.
        if repo.embedding_model is None:
            repo.embedding_model = model_slug(choice)
            repo.embedding_dim = choice.dim
        elif repo.embedding_dim != choice.dim:
            logger.warning(
                "embed_issue: repo pinned to dim=%s but current provider returns dim=%s; skipping",
                repo.embedding_dim,
                choice.dim,
            )
            return

        text_to_embed = f"{title}\n\n{body}".strip()
        vector = await provider.embed(text_to_embed)
        if len(vector) != choice.dim:
            logger.warning(
                "embed_issue: provider returned dim=%s, expected %s",
                len(vector),
                choice.dim,
            )
            return

        dim_col = _dim_column(choice.dim)
        all_cols = {"embedding_1536", "embedding_768", "embedding_384"}
        other_cols = all_cols - {dim_col}
        values = {
            "repo_id": repo_id,
            "issue_number": issue_number,
            "title": title[:500],
            "body_excerpt": (body or "")[:2000],
            dim_col: vector,
            "updated_at": datetime.now(UTC),
        }
        for oc in other_cols:
            values[oc] = None
        stmt = pg_insert(IssueEmbedding).values(values)
        update_set = {
            "title": stmt.excluded.title,
            "body_excerpt": stmt.excluded.body_excerpt,
            dim_col: getattr(stmt.excluded, dim_col),
            "updated_at": datetime.now(UTC),
        }
        for oc in other_cols:
            update_set[oc] = None
        stmt = stmt.on_conflict_do_update(
            constraint="uq_issue_embedding",
            set_=update_set,
        )
        await session.execute(stmt)
        await session.commit()
        logger.info("embed_issue wrote %s#%s (dim=%s)", repo.full_name, issue_number, choice.dim)
