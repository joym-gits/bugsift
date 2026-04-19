"""Tests for the repo-analysis feature.

- Analyser happy-path: fixed LLM stubs → structured result + mermaid.
- API endpoints: kick / get / corrections enforce ownership and state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from bugsift.analysis import analyzer as analyzer_mod
from bugsift.analysis.analyzer import analyze_repo
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    Installation,
    Repo,
    RepoAnalysis,
    User,
)
from bugsift.github import rate_limit
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


@dataclass
class _ScriptedProvider(LLMProvider):
    """Replays a queue of pre-canned responses. Prompts are inspected so
    tests can assert the analyser called us with file / dir / synthesis
    prompts in the expected order."""

    responses: list[str]
    name: str = "stub"
    received_prompts: list[str] | None = None

    def __post_init__(self) -> None:
        self.received_prompts = []

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        assert self.received_prompts is not None
        self.received_prompts.append(messages[-1].content)
        if not self.responses:
            raise RuntimeError("scripted provider ran out of responses")
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model="stub-model",
            usage=Usage(prompt_tokens=10, completion_tokens=10, cost_usd=0.0),
        )

    async def embed(self, text, *, model=None):
        raise NotImplementedError


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


@pytest_asyncio.fixture
async def indexed_repo(session, logged_in: User, monkeypatch: pytest.MonkeyPatch):
    """CodeChunk has pgvector columns we don't load on SQLite. Patch the
    DB loader so the analyser sees a deterministic file set without
    needing real chunks in the test DB."""
    install = Installation(github_installation_id=1, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)

    fake_chunks = [
        ("backend/app.py", "def start(): ...", "python"),
        ("backend/util.py", "def helper(): return 42", "python"),
        ("frontend/index.ts", "export const APP = 'acme';", "typescript"),
    ]

    async def _fake_load(_session, repo_id: int):
        assert repo_id == repo.id
        return fake_chunks

    monkeypatch.setattr(analyzer_mod, "_load_file_chunks", _fake_load)
    return repo


@pytest.mark.asyncio
async def test_analyze_repo_returns_structured_result(session, indexed_repo: Repo):
    # 3 file summaries, 2 dir summaries, 1 synthesis response.
    synth = json.dumps(
        {
            "summary": "A tiny web app.",
            "components": [
                {
                    "name": "Backend",
                    "path": "backend",
                    "role": "App entrypoint and helpers.",
                    "citations": ["backend/app.py:1", "backend/util.py:1"],
                },
                {
                    "name": "Frontend",
                    "path": "frontend",
                    "role": "TS entrypoint.",
                    "citations": ["frontend/index.ts:1"],
                },
            ],
            "entry_points": [{"name": "start", "file": "backend/app.py", "note": "main"}],
            "dependencies": [],
            "flows": [],
            "mermaid_overview": "graph TD\n  Backend --> Frontend",
        }
    )
    provider = _ScriptedProvider(
        responses=[
            "Entrypoint for the backend app.",
            "Misc helpers used by app.py.",
            "Frontend bundle entry.",
            "Directory holding the backend app and helpers.",
            "Frontend bundle root.",
            synth,
        ]
    )

    result = await analyze_repo(session, repo_id=indexed_repo.id, provider=provider)

    assert "Backend" in result.structured["components"][0]["name"]
    assert result.mermaid_overview.startswith("graph TD")
    assert len(result.files) == 3
    assert len(result.directories) == 2
    # Every directory summary passed its file list into the synthesis.
    assert "backend/app.py" in (provider.received_prompts or [])[-1]


@pytest.mark.asyncio
async def test_analyze_repo_skips_repos_without_chunks(
    session, logged_in: User, monkeypatch: pytest.MonkeyPatch
):
    install = Installation(github_installation_id=2, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=2,
        full_name="acme/empty",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)

    async def _empty(_session, repo_id: int):
        return []

    monkeypatch.setattr(analyzer_mod, "_load_file_chunks", _empty)

    with pytest.raises(ValueError, match="no indexed code_chunks"):
        await analyze_repo(
            session, repo_id=repo.id, provider=_ScriptedProvider(responses=[])
        )


@pytest.mark.asyncio
async def test_analyze_repo_fallback_when_synthesis_malformed(
    session, indexed_repo: Repo
):
    """If the synthesis model returns unparseable JSON we still return
    a renderable result — the dashboard should never get a 500."""
    provider = _ScriptedProvider(
        responses=[
            "A", "B", "C", "dir a", "dir b",
            "I am not JSON, sorry.",
        ]
    )
    result = await analyze_repo(session, repo_id=indexed_repo.id, provider=provider)
    assert "components" in result.structured
    assert len(result.structured["components"]) >= 1
    assert result.mermaid_overview.startswith("graph TD")


def test_kick_analysis_404_for_other_users_app(client, logged_in: User, session):
    # App owned by a different user.
    import asyncio

    async def _seed() -> int:
        other = User(github_id=2, github_login="other", email=None)
        session.add(other)
        await session.flush()
        row = FeedbackApp(
            user_id=other.id,
            name="other",
            public_key="pk_other",
        )
        session.add(row)
        await session.commit()
        return row.id

    other_id = asyncio.get_event_loop().run_until_complete(_seed())
    r = client.post(f"/feedback/apps/{other_id}/analyze")
    assert r.status_code == 404


@pytest_asyncio.fixture
async def app_for_analysis(client, logged_in: User, session):
    install = Installation(github_installation_id=3, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=3,
        full_name="acme/site",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    app = FeedbackApp(
        user_id=logged_in.id,
        name="site",
        public_key="pk_site",
        default_repo_id=repo.id,
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return app, repo


def test_kick_analysis_requires_default_repo(client, logged_in: User, session):
    import asyncio

    async def _seed() -> int:
        row = FeedbackApp(
            user_id=logged_in.id,
            name="unbound",
            public_key="pk_unbound",
        )
        session.add(row)
        await session.commit()
        return row.id

    app_id = asyncio.get_event_loop().run_until_complete(_seed())
    r = client.post(f"/feedback/apps/{app_id}/analyze")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_kick_analysis_creates_pending_row(
    client, app_for_analysis, session, monkeypatch: pytest.MonkeyPatch
):
    app, repo = app_for_analysis
    captured: list[int] = []
    from bugsift.workers import enqueue as enq

    monkeypatch.setattr(
        enq, "enqueue_analyze_feedback_app", lambda app_id: captured.append(app_id)
    )

    r = client.post(f"/feedback/apps/{app.id}/analyze")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["branch"] == "main"

    analysis = (
        await session.execute(select(RepoAnalysis).where(RepoAnalysis.repo_id == repo.id))
    ).scalar_one()
    assert analysis.status == "pending"
    assert captured == [app.id]


def test_get_analysis_when_absent_returns_null(client, app_for_analysis):
    app, _ = app_for_analysis
    r = client.get(f"/feedback/apps/{app.id}/analysis")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_correction_appends_override(client, app_for_analysis, session):
    app, repo = app_for_analysis
    analysis = RepoAnalysis(
        repo_id=repo.id,
        branch="main",
        status="ready",
        structured_json={"summary": "old"},
        mermaid_src="graph TD",
    )
    session.add(analysis)
    await session.commit()

    r = client.post(
        f"/feedback/apps/{app.id}/analysis/corrections",
        json={"note": "worker queue is Kafka, not Redis"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overrides"] == ["worker queue is Kafka, not Redis"]
    assert body["status"] == "ready"  # override alone doesn't re-run


@pytest.mark.asyncio
async def test_correction_rejected_without_existing_analysis(
    client, app_for_analysis
):
    app, _ = app_for_analysis
    r = client.post(
        f"/feedback/apps/{app.id}/analysis/corrections",
        json={"note": "x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_app_sets_target_branch(
    client, app_for_analysis, session
):
    app, repo = app_for_analysis
    r = client.patch(
        f"/feedback/apps/{app.id}",
        json={"target_branch": "develop"},
    )
    assert r.status_code == 200
    assert r.json()["target_branch"] == "develop"
    await session.refresh(app)
    assert app.target_branch == "develop"
