"""Step — Regression correlation.

Runs after retrieval + reproduction, when ``state.suspected_files`` is
populated. Asks the regression correlator which recent pushes touched
any of those files, and attaches the answers to the state so the card
writer persists them and the UI can surface a "Possible cause" section.

Cheap: one indexed SQL query, no LLM call. Safe to run even when we
have zero push events — it returns an empty list and the step is a
no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.state import RegressionSuspectRecord, TriageState
from bugsift.regression.correlator import find_regression_suspects

logger = logging.getLogger(__name__)

STEP_NAME = "regression"


async def run(
    state: TriageState,
    *,
    session: AsyncSession,
    reference_time: datetime | None = None,
) -> TriageState:
    if not state.suspected_files:
        return state
    suspects = await find_regression_suspects(
        session,
        repo_id=state.repo_id,
        suspected_paths=[f.file_path for f in state.suspected_files],
        reference_time=reference_time or datetime.now(UTC),
    )
    state.regression_suspects = [
        RegressionSuspectRecord(
            commit_sha=s.commit_sha,
            short_sha=s.short_sha,
            message_first_line=s.message_first_line,
            author_name=s.author_name,
            author_login=s.author_login,
            pushed_at_iso=s.pushed_at.isoformat(),
            pr_number=s.pr_number,
            ref=s.ref,
            overlapping_paths=list(s.overlapping_paths),
        )
        for s in suspects
    ]
    return state
