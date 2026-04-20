from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bugsift.api.deps import get_session
from bugsift.api.main import create_app
from bugsift.config import get_settings
from bugsift.db.models import (
    Base,
    FeedbackApp,
    FeedbackDigest,
    FeedbackReport,
    GithubAppCredentials,
    Installation,
    LLMUsage,
    PushEvent,
    SlackDestination,
    Repo,
    RepoAnalysis,
    RepoAnalysisChatMessage,
    RepoConfig,
    TicketDestination,
    TriageCard,
    User,
    UserApiKey,
)
from bugsift.github import config as github_app_config
from bugsift.github import smee as github_smee
from bugsift.security import crypto

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(s, "session_secret", "test-session-secret-abcdef")
    monkeypatch.setattr(s, "env", "development")
    monkeypatch.setattr(s, "github_app_client_id", "")
    monkeypatch.setattr(s, "github_app_client_secret", "")
    monkeypatch.setattr(s, "github_app_webhook_secret", "")
    # Smee module pokes Redis in /status; stub the lookups for tests.
    async def _no_url() -> str | None:
        return None

    monkeypatch.setattr(github_smee, "get_tunnel_url", _no_url)
    monkeypatch.setattr(github_smee, "forwarder_status", lambda: {"running": False, "tunnel_url": None})
    crypto._fernet.cache_clear()
    github_app_config.clear_cache()
    yield
    crypto._fernet.cache_clear()
    github_app_config.clear_cache()


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator:
    """Fresh in-memory SQLite per test, creating just the Phase-2 tables.

    pgvector columns can't run on SQLite, so we intentionally skip CodeChunk
    and IssueEmbedding tables — those get coverage in phase 6.
    """
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                UserApiKey.__table__,
                Installation.__table__,
                Repo.__table__,
                RepoConfig.__table__,
                TriageCard.__table__,
                LLMUsage.__table__,
                GithubAppCredentials.__table__,
                FeedbackApp.__table__,
                FeedbackReport.__table__,
                FeedbackDigest.__table__,
                RepoAnalysis.__table__,
                RepoAnalysisChatMessage.__table__,
                PushEvent.__table__,
                SlackDestination.__table__,
                TicketDestination.__table__,
            ],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncIterator[TestClient]:
    maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
