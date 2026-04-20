"""Step — Suggest assignees from CODEOWNERS.

Runs after retrieval (we need ``state.suspected_files`` populated) and
before the comment step. Zero LLM calls — pure string matching against
the repo's cached CODEOWNERS text.

No network hit in this step; the CODEOWNERS file is cached on the repo
row by :mod:`bugsift.workers.codeowners`. If the cache is missing
(fresh install that hasn't finished refreshing yet) this step is a
silent no-op — better to ship a card with no assignees than to wait.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.state import TriageState
from bugsift.db.models import Repo
from bugsift.github.codeowners import owners_for_files, parse

logger = logging.getLogger(__name__)


async def run(
    state: TriageState, *, session: AsyncSession
) -> TriageState:
    if not state.suspected_files:
        return state
    repo = await session.get(Repo, state.repo_id)
    if repo is None or not repo.codeowners_text:
        return state
    try:
        rules = parse(repo.codeowners_text)
    except Exception:
        logger.exception(
            "codeowners parse failed for repo_id=%s; skipping assignment",
            state.repo_id,
        )
        return state
    paths = [f.file_path for f in state.suspected_files]
    users = owners_for_files(rules, paths)
    if users:
        state.suggested_assignees = users
        logger.info(
            "codeowners: repo_id=%s suggested %d assignee(s): %s",
            state.repo_id,
            len(users),
            users,
        )
    return state
