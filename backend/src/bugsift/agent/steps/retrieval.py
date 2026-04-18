"""Step 4 — Codebase retrieval.

Runs only when classification is ``bug`` and the pipeline reached this point
without a confirmed duplicate. Embeds the issue body, cosine-searches the
repo's indexed ``code_chunks``, and hands the top 10 to an LLM call that
picks the 3\u20135 most likely relevant. Skips cleanly if no embedding provider
is available, if the repo has no chunks indexed yet, or if the classifier
didn't flag this as a bug.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.prompts import render
from bugsift.agent.state import LLMCallRecord, SuspectedFile, TriageState
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider
from bugsift.retrieval.search import nearest_chunks

logger = logging.getLogger(__name__)

STEP_NAME = "retrieval"
TOP_K_CHUNKS = 10
MAX_SUSPECTED = 5


class EmbedProvider(Protocol):
    async def embed(self, text: str, *, model: str | None = ...) -> list[float]: ...


async def run(
    state: TriageState,
    *,
    session: AsyncSession,
    embed_provider: EmbedProvider | None,
    embedding_dim: int | None,
    llm_provider: LLMProvider,
) -> TriageState:
    if state.classification != "bug":
        return state
    if embed_provider is None or embedding_dim is None:
        return state

    query = f"{state.issue_title}\n\n{state.issue_body}".strip()
    vector = await embed_provider.embed(query)
    if len(vector) != embedding_dim:
        logger.warning(
            "retrieval: embedder returned dim=%s, expected %s; skipping",
            len(vector),
            embedding_dim,
        )
        return state

    chunks = await nearest_chunks(
        session,
        repo_id=state.repo_id,
        dim=embedding_dim,
        query_vector=vector,
        limit=TOP_K_CHUNKS,
    )
    if not chunks:
        return state

    prompt = render(
        "retrieval.j2",
        repo_full_name=state.repo_full_name,
        issue_number=state.issue_number,
        issue_title=state.issue_title,
        issue_body=state.issue_body,
        chunks=chunks,
    )
    response = await llm_provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=800,
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
        raw_items = parsed.get("suspected_files") or []
        if not isinstance(raw_items, list):
            raise ValueError("suspected_files must be an array")
        allowed_paths = {c.file_path for c in chunks}
        suspected: list[SuspectedFile] = []
        for item in raw_items[:MAX_SUSPECTED]:
            path = str(item["file_path"]).strip()
            line_range = str(item["line_range"]).strip()
            rationale = str(item.get("rationale") or "").strip()
            if path not in allowed_paths:
                # Model invented a path that wasn't in the candidates.
                continue
            suspected.append(SuspectedFile(path, line_range, rationale))
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(
            "retrieval: malformed response for %s#%s: %s",
            state.repo_full_name,
            state.issue_number,
            e,
        )
        return state

    state.suspected_files = suspected
    return state
