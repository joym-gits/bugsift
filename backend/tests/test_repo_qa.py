"""Tests for the repo Q&A feature."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.analysis import qa as qa_mod
from bugsift.analysis.qa import Citation, answer_question
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    Installation,
    Repo,
    RepoAnalysis,
    RepoAnalysisChatMessage,
    User,
)
from bugsift.github import rate_limit
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage
from bugsift.retrieval.search import SimilarChunk


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    client.app.dependency_overrides[get_optional_user] = _fake_user
    yield user
    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_optional_user, None)


class _StubLLM(LLMProvider):
    name = "stub"

    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        return LLMResponse(
            content=self._content,
            model="stub-model",
            usage=Usage(prompt_tokens=80, completion_tokens=30, cost_usd=0.0004),
        )

    async def embed(self, text, *, model=None):
        raise NotImplementedError


class _StubEmbedder:
    def __init__(self, vec: list[float]) -> None:
        self._vec = vec

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        return self._vec


@pytest.mark.asyncio
async def test_answer_question_parses_json_and_filters_invalid_citations(
    session, monkeypatch: pytest.MonkeyPatch
):
    async def fake_nearest(*args, **kwargs):
        return [
            SimilarChunk("app/auth.py", 10, 40, "def login(): ...", 0.9),
        ]

    monkeypatch.setattr(qa_mod, "nearest_chunks", fake_nearest)

    analysis = RepoAnalysis(
        id=1,
        repo_id=1,
        branch="main",
        status="ready",
        structured_json={
            "summary": "An auth-heavy tiny service.",
            "components": [{"name": "Auth", "path": "app/auth", "role": "login"}],
        },
    )
    llm_payload = json.dumps(
        {
            "answer": "Login lives in `app/auth.py` — see `login()`.",
            "citations": [
                {"file_path": "app/auth.py", "line_range": "10-40"},
                # Invented — must be dropped.
                {"file_path": "made/up.py", "line_range": "1-1"},
            ],
        }
    )
    result = await answer_question(
        session,
        analysis=analysis,
        question="Where does auth happen?",
        history=[],
        provider=_StubLLM(llm_payload),
        embed_provider=_StubEmbedder([0.1] * 384),
        embedding_dim=384,
    )
    assert "Login lives" in result.answer
    assert result.citations == [
        Citation(file_path="app/auth.py", line_range="10-40")
    ]


@pytest.mark.asyncio
async def test_answer_question_falls_back_to_plain_text_on_bad_json(
    session, monkeypatch: pytest.MonkeyPatch
):
    async def fake_nearest(*args, **kwargs):
        return []

    monkeypatch.setattr(qa_mod, "nearest_chunks", fake_nearest)
    analysis = RepoAnalysis(
        id=1,
        repo_id=1,
        branch="main",
        status="ready",
        structured_json={"summary": "x"},
    )
    result = await answer_question(
        session,
        analysis=analysis,
        question="tell me something",
        history=[],
        provider=_StubLLM("this is not JSON at all"),
        embed_provider=_StubEmbedder([0.1] * 384),
        embedding_dim=384,
    )
    assert "not JSON" in result.answer
    assert result.citations == []


@pytest.mark.asyncio
async def test_answer_question_rejects_empty_question(session):
    analysis = RepoAnalysis(
        id=1, repo_id=1, branch="main", status="ready", structured_json={}
    )
    with pytest.raises(ValueError):
        await answer_question(
            session,
            analysis=analysis,
            question="   ",
            history=[],
            provider=_StubLLM("{}"),
            embed_provider=_StubEmbedder([]),
            embedding_dim=384,
        )


@pytest_asyncio.fixture
async def app_with_ready_analysis(session, logged_in: User):
    install = Installation(github_installation_id=1, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
        embedding_model="local:BAAI/bge-small-en-v1.5",
        embedding_dim=384,
    )
    session.add(repo)
    await session.flush()
    app = FeedbackApp(
        user_id=logged_in.id,
        name="web",
        public_key="pk_web",
        default_repo_id=repo.id,
    )
    session.add(app)
    await session.flush()
    analysis = RepoAnalysis(
        repo_id=repo.id,
        branch="main",
        status="ready",
        structured_json={"summary": "ok"},
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(app)
    await session.refresh(analysis)
    return app, repo, analysis


def test_list_chats_empty(client, app_with_ready_analysis):
    app, *_ = app_with_ready_analysis
    r = client.get(f"/feedback/apps/{app.id}/chats")
    assert r.status_code == 200
    assert r.json() == []


def test_chats_require_ready_analysis(client, logged_in: User, session):
    import asyncio

    async def _seed_no_analysis() -> int:
        install = Installation(github_installation_id=2, user_id=logged_in.id)
        session.add(install)
        await session.flush()
        repo = Repo(
            installation_id=install.id,
            github_repo_id=2,
            full_name="acme/other",
            default_branch="main",
            indexing_status="pending",
        )
        session.add(repo)
        await session.flush()
        app = FeedbackApp(
            user_id=logged_in.id,
            name="other",
            public_key="pk_other",
            default_repo_id=repo.id,
        )
        session.add(app)
        await session.commit()
        return app.id

    app_id = asyncio.get_event_loop().run_until_complete(_seed_no_analysis())
    r = client.get(f"/feedback/apps/{app_id}/chats")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_clear_chats(client, app_with_ready_analysis, session):
    app, _repo, analysis = app_with_ready_analysis
    # Seed some messages directly.
    session.add_all([
        RepoAnalysisChatMessage(
            analysis_id=analysis.id, role="user", content="q1"
        ),
        RepoAnalysisChatMessage(
            analysis_id=analysis.id,
            role="assistant",
            content="a1",
        ),
    ])
    await session.commit()

    r = client.get(f"/feedback/apps/{app.id}/chats")
    assert len(r.json()) == 2

    r_del = client.delete(f"/feedback/apps/{app.id}/chats")
    assert r_del.status_code == 204
    assert client.get(f"/feedback/apps/{app.id}/chats").json() == []
