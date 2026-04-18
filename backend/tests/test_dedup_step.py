from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from bugsift.agent.state import TriageState
from bugsift.agent.steps import dedup as dedup_step
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage


class _StubJudge(LLMProvider):
    name = "stub"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.last: list[ChatMessage] | None = None

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        self.last = messages
        return self._response

    async def embed(self, text, *, model=None):
        raise NotImplementedError


class _StubEmbedder:
    def __init__(self, vec: list[float]) -> None:
        self._vec = vec
        self.calls: list[str] = []

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        self.calls.append(text)
        return self._vec


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        usage=Usage(prompt_tokens=50, completion_tokens=30, cost_usd=0.0005),
    )


def _state() -> TriageState:
    return TriageState(
        repo_id=1,
        repo_full_name="o/r",
        issue_number=10,
        issue_title="widget crashes",
        issue_body="stacktrace here",
        classification="bug",
        confidence=0.9,
    )


@pytest_asyncio.fixture
async def _seeded_candidates(session):
    """Seed one near and one far issue embedding so nearest_issues has data."""

    from bugsift.db.models import Installation, Repo, User

    user = User(github_id=99, github_login="u", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=99, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=99,
        full_name="o/r",
        default_branch="main",
        indexing_status="ready",
        embedding_model="openai:text-embedding-3-small",
        embedding_dim=1536,
    )
    session.add(repo)
    await session.flush()
    await session.commit()

    # SQLite can't store pgvector blobs, so skip any DB seeding — instead
    # we exercise the dedup step against a monkey-patched nearest_issues that
    # returns preset candidates. See each test's monkeypatch.
    return repo


async def test_dedup_skips_when_no_embedder(session) -> None:
    state = _state()
    out = await dedup_step.run(
        state,
        session=session,
        embed_provider=None,
        embedding_dim=None,
        judge_provider=_StubJudge(_resp("{}")),
    )
    assert out.duplicates == []
    assert out.status == "running"


async def test_dedup_no_candidates_returns_unchanged(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_nearest(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    monkeypatch.setattr(dedup_step, "nearest_issues", fake_nearest)
    judge = _StubJudge(_resp("{}"))
    out = await dedup_step.run(
        _state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        judge_provider=judge,
    )
    assert out.duplicates == []
    assert out.status == "running"
    assert judge.last is None  # judge not invoked when no candidates


async def test_dedup_short_circuits_on_high_confidence_duplicate(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bugsift.retrieval.search import SimilarIssue

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarIssue]:
        return [SimilarIssue(7, "older title", "old body", 0.92)]

    monkeypatch.setattr(dedup_step, "nearest_issues", fake_nearest)
    judge = _StubJudge(
        _resp('{"duplicates":[{"issue_number":7,"confidence":0.95,"rationale":"same repro"}]}')
    )
    out = await dedup_step.run(
        _state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        judge_provider=judge,
    )
    assert out.status == "complete"
    assert out.proposed_action == "comment_and_close"
    assert out.draft_comment and "#7" in out.draft_comment


async def test_dedup_does_not_short_circuit_on_low_confidence(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bugsift.retrieval.search import SimilarIssue

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarIssue]:
        return [SimilarIssue(7, "older title", "old body", 0.8)]

    monkeypatch.setattr(dedup_step, "nearest_issues", fake_nearest)
    judge = _StubJudge(
        _resp('{"duplicates":[{"issue_number":7,"confidence":0.5,"rationale":"topically close"}]}')
    )
    out = await dedup_step.run(
        _state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        judge_provider=judge,
    )
    assert out.status == "running"
    assert len(out.duplicates) == 1
    assert out.duplicates[0].confidence == 0.5


async def test_dedup_handles_malformed_judge_response(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bugsift.retrieval.search import SimilarIssue

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarIssue]:
        return [SimilarIssue(7, "t", "b", 0.9)]

    monkeypatch.setattr(dedup_step, "nearest_issues", fake_nearest)
    judge = _StubJudge(_resp("not json"))
    out = await dedup_step.run(
        _state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        judge_provider=judge,
    )
    assert out.status == "running"
    assert out.duplicates == []
