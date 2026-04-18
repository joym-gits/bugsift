from __future__ import annotations

from typing import Any

import pytest

from bugsift.agent.state import TriageState
from bugsift.agent.steps import retrieval as retrieval_step
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage
from bugsift.retrieval.search import SimilarChunk


class _StubLLM(LLMProvider):
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

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        return self._vec


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        usage=Usage(prompt_tokens=200, completion_tokens=60, cost_usd=0.0008),
    )


def _bug_state() -> TriageState:
    return TriageState(
        repo_id=1,
        repo_full_name="octo/widget",
        issue_number=77,
        issue_title="crash in Foo.bar when x=None",
        issue_body="Traceback (most recent call last):\n ...",
        classification="bug",
        confidence=0.9,
    )


async def test_skips_when_not_a_bug(session) -> None:
    state = _bug_state()
    state.classification = "question"
    out = await retrieval_step.run(
        state,
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=_StubLLM(_resp("{}")),
    )
    assert out.suspected_files == []
    assert out.status == "running"


async def test_skips_without_embedder(session) -> None:
    out = await retrieval_step.run(
        _bug_state(),
        session=session,
        embed_provider=None,
        embedding_dim=None,
        llm_provider=_StubLLM(_resp("{}")),
    )
    assert out.suspected_files == []


async def test_skips_when_no_chunks(session, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        return []

    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)
    llm = _StubLLM(_resp("{}"))
    out = await retrieval_step.run(
        _bug_state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert out.suspected_files == []
    assert llm.last is None  # judge not invoked when no candidates


async def test_picks_files_from_candidates(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = [
        SimilarChunk("src/foo.py", 10, 50, "def bar(...): ...", 0.91),
        SimilarChunk("src/bar.py", 20, 40, "class Foo: ...", 0.82),
        SimilarChunk("tests/conftest.py", 1, 15, "@pytest.fixture", 0.55),
    ]

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        return chunks

    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)
    llm = _StubLLM(
        _resp(
            '{"suspected_files":['
            '{"file_path":"src/foo.py","line_range":"10-50","rationale":"defines Foo.bar"},'
            '{"file_path":"src/bar.py","line_range":"20-40","rationale":"Foo class body"}'
            "]}"
        )
    )
    out = await retrieval_step.run(
        _bug_state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert len(out.suspected_files) == 2
    assert out.suspected_files[0].file_path == "src/foo.py"
    assert out.suspected_files[0].line_range == "10-50"
    assert out.suspected_files[0].rationale == "defines Foo.bar"


async def test_drops_invented_paths(session, monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [SimilarChunk("src/foo.py", 10, 50, "def bar(...): ...", 0.91)]

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        return chunks

    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)
    llm = _StubLLM(
        _resp(
            '{"suspected_files":['
            '{"file_path":"src/foo.py","line_range":"10-50","rationale":"real"},'
            '{"file_path":"src/invented.py","line_range":"1-10","rationale":"made up"}'
            "]}"
        )
    )
    out = await retrieval_step.run(
        _bug_state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert [s.file_path for s in out.suspected_files] == ["src/foo.py"]


async def test_malformed_response_leaves_state_unchanged(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = [SimilarChunk("src/foo.py", 10, 50, "content", 0.91)]

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        return chunks

    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)
    llm = _StubLLM(_resp("not json"))
    out = await retrieval_step.run(
        _bug_state(),
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert out.suspected_files == []
    assert out.status == "running"
