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


async def test_seeds_chunks_from_stack_trace_in_body(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the issue body contains a stack trace, the step should pull
    those files from ``code_chunks`` directly and pass them to the judge
    alongside the embedding matches."""
    hint_paths_seen: list[list[str]] = []

    async def fake_chunks_for_paths(
        session, *, repo_id: int, paths: list[str], limit_per_path: int = 3
    ) -> list[SimilarChunk]:
        hint_paths_seen.append(paths)
        return [
            SimilarChunk("app/services/payments.py", 40, 55, "def charge(...):", 1.0),
        ]

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        # A different file — the embedding top-K and the hint-seeded set
        # should union and be presented together.
        return [SimilarChunk("unrelated/module.py", 10, 30, "...", 0.60)]

    monkeypatch.setattr(retrieval_step, "chunks_for_paths", fake_chunks_for_paths)
    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)

    state = _bug_state()
    state.issue_body = (
        'Traceback (most recent call last):\n'
        '  File "app/services/payments.py", line 47, in charge\n'
        "    foo()\n"
        "TypeError: bad\n"
    )

    llm = _StubLLM(
        _resp(
            '{"suspected_files":[{"file_path":"app/services/payments.py",'
            '"line_range":"40-55","rationale":"traceback names this file"}]}'
        )
    )
    out = await retrieval_step.run(
        state,
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert hint_paths_seen == [["app/services/payments.py"]]
    assert [s.file_path for s in out.suspected_files] == ["app/services/payments.py"]


async def test_identifier_search_augments_candidates(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backtick identifiers in the issue body should trigger a substring
    search against code chunks and add those to the candidate list."""
    tokens_seen: list[list[str]] = []

    async def fake_tokens(
        session, *, repo_id: int, tokens: list[str], limit_per_token: int = 2
    ) -> list[SimilarChunk]:
        tokens_seen.append(tokens)
        return [SimilarChunk("src/renderer.tsx", 10, 40, "function renderList()", 0.9)]

    async def fake_nearest(*args: Any, **kwargs: Any) -> list[SimilarChunk]:
        return []

    monkeypatch.setattr(retrieval_step, "chunks_containing_tokens", fake_tokens)
    monkeypatch.setattr(retrieval_step, "nearest_chunks", fake_nearest)

    state = _bug_state()
    state.issue_body = "The `renderList` function crashes on empty arrays."

    llm = _StubLLM(
        _resp(
            '{"suspected_files":[{"file_path":"src/renderer.tsx",'
            '"line_range":"10-40","rationale":"defines renderList"}]}'
        )
    )
    out = await retrieval_step.run(
        state,
        session=session,
        embed_provider=_StubEmbedder([0.1] * 1536),
        embedding_dim=1536,
        llm_provider=llm,
    )
    assert tokens_seen and "renderList" in tokens_seen[0]
    assert [s.file_path for s in out.suspected_files] == ["src/renderer.tsx"]


async def test_refine_with_repro_appends_traceback_files(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After reproduction, any file named in the repro traceback that
    isn't already suspected should be appended deterministically."""
    from bugsift.agent.state import SuspectedFile

    async def fake_chunks_for_paths(
        session, *, repo_id: int, paths: list[str], limit_per_path: int = 3
    ) -> list[SimilarChunk]:
        return [SimilarChunk("app/db.py", 5, 12, "def save(): ...", 1.0)]

    monkeypatch.setattr(retrieval_step, "chunks_for_paths", fake_chunks_for_paths)

    state = _bug_state()
    state.suspected_files = [
        SuspectedFile(file_path="app/api.py", line_range="1-20", rationale="from retrieval")
    ]
    state.reproduction_log = (
        'Traceback (most recent call last):\n'
        '  File "app/db.py", line 8, in save\n'
        '    raise RuntimeError\n'
    )

    out = await retrieval_step.refine_with_repro(state, session=session)
    paths = [s.file_path for s in out.suspected_files]
    assert paths == ["app/api.py", "app/db.py"]
    assert "reproduction traceback" in out.suspected_files[1].rationale


async def test_refine_with_repro_is_noop_without_log(session) -> None:
    state = _bug_state()
    state.reproduction_log = None
    state.suspected_files = []
    out = await retrieval_step.refine_with_repro(state, session=session)
    assert out.suspected_files == []


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
