"""Repo Q&A over the stored analysis + indexed code.

One public function — :func:`answer_question` — takes a live
:class:`RepoAnalysis` plus a user question, retrieves the top-K
nearest code chunks, and calls the LLM with everything grounded in a
fixed prompt that demands a JSON answer + citations.

Retrieval reuses ``nearest_chunks`` so embeddings we already have stay
the only source of truth. The prompt pins the LLM to file paths that
actually appeared in the excerpts — invented paths are dropped server-
side before we render the message to the user.

History is truncated to the last N turns to keep the prompt budget
bounded; the dashboard can still show the full conversation from the
DB.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.prompts import render
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.db.models import RepoAnalysis
from bugsift.llm.base import ChatMessage, LLMProvider
from bugsift.retrieval.search import nearest_chunks

logger = logging.getLogger(__name__)

TOP_K_CHUNKS = 6
MAX_HISTORY_TURNS = 8
MAX_CITATIONS = 4


@dataclass(frozen=True)
class Citation:
    file_path: str
    line_range: str


@dataclass
class AnswerResult:
    answer: str
    citations: list[Citation]
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    model: str


class Embedder:
    """Duck-typed bit of the :class:`LLMProvider` we actually need."""

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:  # noqa: D401
        raise NotImplementedError


async def answer_question(
    session: AsyncSession,
    *,
    analysis: RepoAnalysis,
    question: str,
    history: list[dict[str, str]],
    provider: LLMProvider,
    embed_provider: Embedder,
    embedding_dim: int,
) -> AnswerResult:
    """Run one turn of Q&A. Returns the synthesised answer + citations
    and per-call usage so the caller can persist a chat row."""
    question = question.strip()
    if not question:
        raise ValueError("question is empty")

    # Retrieve context. If the repo has no indexed chunks we still run
    # — the model can answer from the analysis summary + components
    # alone for architectural questions.
    chunks: list = []
    try:
        vector = await embed_provider.embed(question)
        if len(vector) == embedding_dim:
            chunks = await nearest_chunks(
                session,
                repo_id=analysis.repo_id,
                dim=embedding_dim,
                query_vector=vector,
                limit=TOP_K_CHUNKS,
            )
        else:
            logger.warning(
                "qa: embedder returned dim=%s expected %s; skipping retrieval",
                len(vector),
                embedding_dim,
            )
    except Exception:
        logger.exception("qa: retrieval failed; answering from analysis alone")

    structured = analysis.structured_json or {}
    prompt = render(
        "qa.j2",
        analysis_summary=structured.get("summary"),
        components=structured.get("components") or [],
        chunks=chunks,
        history=history[-MAX_HISTORY_TURNS:],
        question=question,
    )

    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=1200,
        temperature=0.1,
    )

    parsed = _parse_answer(response.content)
    allowed_paths = {c.file_path for c in chunks}
    citations: list[Citation] = []
    for item in parsed.get("citations") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file_path", "")).strip()
        line_range = str(item.get("line_range", "")).strip()
        # Prompt said "only paths that appear in the excerpts"; enforce it.
        if allowed_paths and path not in allowed_paths:
            continue
        if not path:
            continue
        citations.append(Citation(file_path=path, line_range=line_range))
        if len(citations) >= MAX_CITATIONS:
            break

    answer_text = str(parsed.get("answer") or "").strip()
    if not answer_text:
        # Model returned JSON with an empty answer; surface something
        # useful so the UI isn't blank.
        answer_text = (
            "I couldn't answer from the retrieved context. Try rephrasing "
            "the question with a concrete file name or symbol."
        )

    return AnswerResult(
        answer=answer_text,
        citations=citations,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        cost_usd=response.usage.cost_usd,
        model=response.model,
    )


def _parse_answer(raw: str) -> dict:
    try:
        return parse_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        # Models drift — if they answered in prose, fall back to
        # treating the whole string as the answer body. Better to show
        # something than error out on a formatting miss.
        logger.warning(
            "qa: LLM returned non-JSON response; wrapping as plain answer"
        )
        return {"answer": raw.strip()[:4000], "citations": []}
