"""Step 3 — Dedup search + LLM judge.

Embed the incoming issue, cosine-search the repo's existing issue
embeddings, pass the top 5 (with similarity \u2265 0.75) to the LLM judge, and
short-circuit the pipeline if any candidate is confirmed as a duplicate with
confidence \u2265 0.8.

Skips cleanly when no embedding provider is available for the repo. In that
case we leave ``state.duplicates`` empty and let the orchestrator continue
to the comment step.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.prompts import render
from bugsift.agent.state import DuplicateCandidate, LLMCallRecord, TriageState
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider
from bugsift.retrieval.search import nearest_issues

logger = logging.getLogger(__name__)

STEP_NAME = "dedup"
SIMILARITY_THRESHOLD = 0.75
CONFIDENCE_TO_CONFIRM = 0.8
TOP_K = 5


class EmbedProvider(Protocol):
    async def embed(self, text: str, *, model: str | None = ...) -> list[float]: ...


async def run(
    state: TriageState,
    *,
    session: AsyncSession,
    embed_provider: EmbedProvider | None,
    embedding_dim: int | None,
    judge_provider: LLMProvider,
) -> TriageState:
    if embed_provider is None or embedding_dim is None:
        logger.info(
            "dedup: no embedder for %s; skipping", state.repo_full_name
        )
        return state

    query = f"{state.issue_title}\n\n{state.issue_body}".strip()
    vector = await embed_provider.embed(query)
    if len(vector) != embedding_dim:
        logger.warning(
            "dedup: embedder returned dim=%s, expected %s; skipping",
            len(vector),
            embedding_dim,
        )
        return state

    candidates = await nearest_issues(
        session,
        repo_id=state.repo_id,
        dim=embedding_dim,
        query_vector=vector,
        exclude_issue_number=state.issue_number,
        limit=TOP_K,
        min_similarity=SIMILARITY_THRESHOLD,
    )
    if not candidates:
        return state

    prompt = render(
        "dedup.j2",
        new_issue_number=state.issue_number,
        new_issue_title=state.issue_title,
        new_issue_body=state.issue_body,
        candidates=candidates,
    )
    response = await judge_provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=512,
        temperature=0.0,
    )
    state.llm_calls.append(
        LLMCallRecord(
            step=STEP_NAME,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost_usd=response.usage.cost_usd,
        )
    )

    try:
        parsed = parse_json_object(response.content)
        dups_raw = parsed.get("duplicates") or []
        if not isinstance(dups_raw, list):
            raise ValueError("duplicates must be an array")
        parsed_dups: list[DuplicateCandidate] = []
        for d in dups_raw:
            issue_number = int(d["issue_number"])
            confidence = float(d["confidence"])
            rationale = str(d.get("rationale") or "")
            parsed_dups.append(DuplicateCandidate(issue_number, rationale, confidence))
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(
            "dedup: malformed judge response for %s#%s: %s",
            state.repo_full_name,
            state.issue_number,
            e,
        )
        return state

    state.duplicates = parsed_dups
    confirmed = [d for d in parsed_dups if d.confidence >= CONFIDENCE_TO_CONFIRM]
    if confirmed:
        confirmed.sort(key=lambda d: -d.confidence)
        state.short_circuit(f"duplicate of #{confirmed[0].issue_number}")
        state.proposed_action = "comment_and_close"
        state.draft_comment = (
            f"This looks like a duplicate of #{confirmed[0].issue_number}. "
            f"{confirmed[0].rationale} Closing in favour of that issue — please "
            f"reopen if this is a distinct problem."
        )
    return state
