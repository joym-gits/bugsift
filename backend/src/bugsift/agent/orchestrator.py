"""Deterministic triage pipeline.

Steps run in a fixed order. Each step can short-circuit the rest by setting
``state.status = "complete"``. No ReAct loops, no implicit tool routing, no
autonomous planning. If a phase's step isn't implemented yet (e.g. retrieval
/ reproduction), it's a no-op here and will slot in without changing the
surrounding flow.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.state import TriageState
from bugsift.agent.steps import classify as classify_step
from bugsift.agent.steps import comment as comment_step
from bugsift.agent.steps import dedup as dedup_step
from bugsift.agent.steps import retrieval as retrieval_step
from bugsift.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    async def embed(self, text: str, *, model: str | None = ...) -> list[float]: ...


async def run(
    state: TriageState,
    provider: LLMProvider,
    *,
    session: AsyncSession | None = None,
    embed_provider: _Embedder | None = None,
    embedding_dim: int | None = None,
) -> TriageState:
    if state.enabled_steps.get("classify", True):
        state = await classify_step.run(state, provider)
        if state.status == "complete":
            # Spam / low confidence — still draft a short note for the maintainer.
            await _draft_if_possible(state, provider)
            return state

    if session is not None and state.enabled_steps.get("dedup", True):
        state = await dedup_step.run(
            state,
            session=session,
            embed_provider=embed_provider,
            embedding_dim=embedding_dim,
            judge_provider=provider,
        )
        if state.status == "complete":
            # Dedup confirmed a duplicate and already populated draft_comment.
            return state

    if session is not None and state.enabled_steps.get("retrieval", True):
        state = await retrieval_step.run(
            state,
            session=session,
            embed_provider=embed_provider,
            embedding_dim=embedding_dim,
            llm_provider=provider,
        )

    # Phase 8: reproduction (no-op placeholder)

    state = await comment_step.run(state, provider)
    state.status = "complete"
    return state


async def _draft_if_possible(state: TriageState, provider: LLMProvider) -> None:
    """When the pipeline short-circuits, we still want a one-liner on the card
    so the maintainer knows what we decided and why."""
    if state.draft_comment is not None:
        return
    if state.flag_reason == "classified as spam":
        state.draft_comment = "This issue appears to be spam. Recommend closing."
        state.proposed_action = "flag_for_review"
        return
    state.draft_comment = (
        state.flag_reason or "Automated triage could not reach a confident decision."
    )
    state.proposed_action = "flag_for_review"
