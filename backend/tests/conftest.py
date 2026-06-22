"""
Comprehensive pytest configuration with fixtures, factories, and mock services.
Handles database, async operations, authentication, and external service mocking.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any
from unittest import mock

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from faker import Faker

# Suppress StarletteDeprecationWarning about httpx with testclient
# Must be before importing TestClient
warnings.simplefilter("ignore", DeprecationWarning)
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

# Test database configuration
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
fake = Faker()


# ============================================================================
# SETTINGS & ENVIRONMENT FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure test environment with safe defaults."""
    s = get_settings()
    monkeypatch.setattr(s, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(s, "session_secret", "test-session-secret-abcdef")
    monkeypatch.setattr(s, "env", "development")
    monkeypatch.setattr(s, "public_url", "http://localhost:8080")
    monkeypatch.setattr(s, "github_app_id", "test-app-id")
    monkeypatch.setattr(s, "github_app_client_id", "test-client-id")
    monkeypatch.setattr(s, "github_app_client_secret", "test-client-secret")
    monkeypatch.setattr(s, "github_app_webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(s, "github_app_private_key", "test-private-key")
    monkeypatch.setattr(s, "bootstrap_token", "test-bootstrap-token")
    monkeypatch.setattr(s, "trust_proxy", False)
    # Use in-memory Redis URL for tests
    monkeypatch.setattr(s, "redis_url", "redis://localhost:6379/15")

    # Stub out Redis and Smee module lookups
    async def _no_url() -> str | None:
        return None

    monkeypatch.setattr(github_smee, "get_tunnel_url", _no_url)
    monkeypatch.setattr(github_smee, "forwarder_status", lambda: {"running": False, "tunnel_url": None})
    
    # Clear caches
    crypto._fernet.cache_clear()
    github_app_config.clear_cache()
    
    yield
    
    # Cleanup
    crypto._fernet.cache_clear()
    github_app_config.clear_cache()


@pytest.fixture
def settings():
    """Get current test settings."""
    return get_settings()


@pytest.fixture
def fake_data():
    """Faker instance for generating test data."""
    return fake


# ============================================================================
# DATABASE FIXTURES
# ============================================================================


@pytest_asyncio.fixture
async def db_engine():
    """Create fresh in-memory SQLite database per test."""
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
    """Async database session for tests."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        try:
            yield s
        finally:
            await s.rollback()


@pytest_asyncio.fixture
async def app():
    """Create FastAPI test app."""
    return create_app()


@pytest_asyncio.fixture
async def client(app, session) -> AsyncIterator[TestClient]:
    """Test client with database session override."""
    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for pytest-anyio."""
    return "asyncio"


# ============================================================================
# MOCK EXTERNAL SERVICES
# ============================================================================


@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis client to prevent connection errors in tests."""
    with mock.patch("redis.asyncio.from_url") as mock_redis_client, \
         mock.patch("redis.from_url") as mock_sync_redis_client:
        client = mock.AsyncMock()
        client.ping = mock.AsyncMock(return_value=True)
        client.get = mock.AsyncMock(return_value=None)
        client.set = mock.AsyncMock(return_value=True)
        client.setex = mock.AsyncMock(return_value=True)
        client.delete = mock.AsyncMock(return_value=0)
        client.exists = mock.AsyncMock(return_value=0)
        client.expire = mock.AsyncMock(return_value=True)
        client.flushdb = mock.AsyncMock(return_value=True)
        client.keys = mock.AsyncMock(return_value=[])
        client.scan_iter = mock.AsyncMock(return_value=iter([]))
        client.aclose = mock.AsyncMock(return_value=None)
        mock_redis_client.return_value = client
        mock_sync_redis_client.return_value = client
        yield client


@pytest.fixture
def mock_github_api():
    """Mock GitHub API requests."""
    with mock.patch("httpx.AsyncClient") as mock_client:
        yield mock_client.return_value


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic LLM client."""
    with mock.patch("anthropic.Anthropic") as mock_client:
        client = mock.MagicMock()
        client.messages.create.return_value = mock.MagicMock(
            content=[mock.MagicMock(text="Mock response")]
        )
        mock_client.return_value = client
        yield client


@pytest.fixture
def mock_openai():
    """Mock OpenAI LLM client."""
    with mock.patch("openai.OpenAI") as mock_client:
        client = mock.MagicMock()
        client.chat.completions.create.return_value = mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content="Mock response"))]
        )
        mock_client.return_value = client
        yield client


@pytest.fixture
def mock_docker():
    """Mock Docker client."""
    with mock.patch("docker.from_env") as mock_docker_client:
        client = mock.MagicMock()
        container = mock.MagicMock()
        container.wait.return_value = {"StatusCode": 0}
        container.logs.return_value = b"Mock output"
        client.containers.run.return_value = container
        mock_docker_client.return_value = client
        yield client


@pytest.fixture
def mock_slack():
    """Mock Slack API client."""
    with mock.patch("slack_sdk.WebClient") as mock_slack_client:
        client = mock.MagicMock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "1234567890.123456"}
        mock_slack_client.return_value = client
        yield client


@pytest.fixture
def mock_embeddings():
    """Mock embedding model."""
    with mock.patch("fastembed.FlagEmbedding") as mock_embed:
        model = mock.MagicMock()
        model.embed.return_value = [[0.1] * 384]  # Mock embedding vector
        mock_embed.return_value = model
        yield model


# ============================================================================
# DATABASE FACTORIES (using direct model construction)
# ============================================================================


@pytest.fixture
async def user_factory(session: AsyncSession):
    """Factory for creating test users."""
    async def create_user(
        github_login: str | None = None,
        email: str | None = None,
        role: str = "triager",
        **kwargs
    ) -> User:
        user = User(
            id=str(uuid.uuid4()),
            github_login=github_login or fake.user_name(),
            email=email or fake.email(),
            role=role,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(user)
        await session.flush()
        return user
    
    return create_user


@pytest.fixture
async def repo_factory(session: AsyncSession, user_factory):
    """Factory for creating test repositories."""
    async def create_repo(
        owner: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        **kwargs
    ) -> Repo:
        if not user_id:
            user = await user_factory()
            user_id = user.id
        
        repo = Repo(
            id=str(uuid.uuid4()),
            name=name or fake.slug(),
            owner=owner or fake.user_name(),
            user_id=user_id,
            github_id=fake.random_int(min=1, max=999999),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(repo)
        await session.flush()
        return repo
    
    return create_repo


@pytest.fixture
async def triage_card_factory(session: AsyncSession, repo_factory):
    """Factory for creating test triage cards."""
    async def create_card(
        repo_id: str | None = None,
        status: str = "pending",
        **kwargs
    ) -> TriageCard:
        if not repo_id:
            repo = await repo_factory()
            repo_id = repo.id
        
        card = TriageCard(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            issue_number=fake.random_int(min=1, max=9999),
            issue_title=fake.sentence(),
            status=status,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(card)
        await session.flush()
        return card
    
    return create_card


@pytest.fixture
async def installation_factory(session: AsyncSession, user_factory):
    """Factory for creating test GitHub App installations."""
    async def create_installation(
        github_id: int | None = None,
        user_id: str | None = None,
        **kwargs
    ) -> Installation:
        if not user_id:
            user = await user_factory()
            user_id = user.id
        
        installation = Installation(
            id=str(uuid.uuid4()),
            github_id=github_id or fake.random_int(min=1, max=999999),
            user_id=user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(installation)
        await session.flush()
        return installation
    
    return create_installation


# ============================================================================
# TEST DATA FIXTURES
# ============================================================================


@pytest.fixture
def github_webhook_payload():
    """Sample GitHub webhook payload."""
    return {
        "action": "opened",
        "issue": {
            "id": 1296269,
            "node_id": "MDU6SXNzdWUxMjk2MjY5",
            "number": 1347,
            "title": "Found a bug",
            "user": {
                "login": "octocat",
                "id": 1,
                "type": "User",
            },
            "body": "This is a test issue body.",
            "created_at": "2021-05-17T20:39:23Z",
            "updated_at": "2021-05-17T20:39:23Z",
        },
        "repository": {
            "id": 1296269,
            "name": "Hello-World",
            "full_name": "octocat/Hello-World",
            "owner": {
                "login": "octocat",
                "id": 1,
                "type": "User",
            },
        },
    }


@pytest.fixture
def slack_webhook_payload():
    """Sample Slack message payload."""
    return {
        "token": "test-token",
        "team_id": "T12345",
        "api_app_id": "A12345",
        "event": {
            "type": "message",
            "channel": "C12345",
            "user": "U12345",
            "text": "Test message",
            "ts": "1234567890.123456",
        },
        "type": "event_callback",
    }


@pytest.fixture
def sample_issue_body():
    """Sample GitHub issue body for testing."""
    return """
## Description
This is a test issue description.

## Steps to Reproduce
1. Step one
2. Step two
3. Step three

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Environment
- OS: Windows 10
- Browser: Chrome
- Version: 1.0.0
    """


@pytest.fixture
def sample_code_snippet():
    """Sample Python code for testing."""
    return '''
def fibonacci(n):
    """Calculate fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, a, b):
        self.result = a + b
        return self.result
    '''


# ============================================================================
# AUTHENTICATION & SECURITY FIXTURES
# ============================================================================


@pytest.fixture
def jwt_token(settings):
    """Generate a test JWT token."""
    import jwt
    from datetime import datetime, timedelta
    
    payload = {
        "sub": "test-user-id",
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


@pytest.fixture
def auth_headers(jwt_token):
    """HTTP headers with authentication token."""
    return {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }


@pytest.fixture
def encryption_key():
    """Generate test encryption key."""
    return Fernet.generate_key()


# ============================================================================
# PERFORMANCE & LOAD TEST HELPERS
# ============================================================================


@pytest.fixture
def benchmark_timer():
    """Simple timer for benchmarking."""
    class BenchmarkTimer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = datetime.utcnow()
        
        def stop(self):
            self.end_time = datetime.utcnow()
            return self.elapsed_ms
        
        @property
        def elapsed_ms(self):
            if self.start_time and self.end_time:
                return (self.end_time - self.start_time).total_seconds() * 1000
            return 0
    
    return BenchmarkTimer()


# ============================================================================
# PYTEST HOOKS
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: unit tests")
    config.addinivalue_line("markers", "integration: integration tests")
    config.addinivalue_line("markers", "api: API endpoint tests")
    config.addinivalue_line("markers", "database: database tests")
    config.addinivalue_line("markers", "auth: authentication tests")
    config.addinivalue_line("markers", "security: security tests")
    config.addinivalue_line("markers", "llm: LLM tests")
    config.addinivalue_line("markers", "performance: performance tests")
    config.addinivalue_line("markers", "smoke: smoke tests")


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton caches between tests."""
    yield
    crypto._fernet.cache_clear()
    github_app_config.clear_cache()
