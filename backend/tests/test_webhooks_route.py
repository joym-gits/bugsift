from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from bugsift.api import webhooks as webhook_route
from bugsift.config import get_settings
from bugsift.db.models import Installation, Repo, RepoConfig
from bugsift.github import rate_limit
from bugsift.github.webhooks import sign_payload


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis_for_rate_limit(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


@pytest.fixture
def _configure_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "wh-secret-abc123"
    monkeypatch.setattr(get_settings(), "github_app_webhook_secret", secret)
    return secret


@pytest.fixture
def _capture_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []
    monkeypatch.setattr(webhook_route, "_enqueue_triage", lambda payload: captured.append(payload))
    return captured


@pytest.fixture(autouse=True)
def _stub_indexing_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indexing + embed jobs hit Redis; stub for unit tests."""
    monkeypatch.setattr(webhook_route, "_enqueue_index_repo", lambda *a, **kw: None)
    monkeypatch.setattr(webhook_route, "_enqueue_index_repo_delta", lambda *a, **kw: None)
    monkeypatch.setattr(webhook_route, "_enqueue_embed_issue", lambda *a, **kw: None)


def _post(client, secret: str, event: str, body: dict):
    raw = json.dumps(body).encode()
    return client.post(
        "/webhooks/github",
        content=raw,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": sign_payload(raw, secret),
            "Content-Type": "application/json",
        },
    )


def test_webhook_503_without_secret(client) -> None:
    r = client.post(
        "/webhooks/github",
        content=b"{}",
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 503


def test_webhook_401_on_bad_signature(client, _configure_webhook_secret) -> None:
    r = client.post(
        "/webhooks/github",
        content=b"{}",
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401


def test_webhook_ping(client, _configure_webhook_secret) -> None:
    r = _post(client, _configure_webhook_secret, "ping", {"zen": "Anything added dilutes everything else."})
    assert r.status_code == 202
    assert r.json() == {"status": "pong"}


@pytest.mark.asyncio
async def test_installation_created_creates_rows(
    client, session, _configure_webhook_secret
) -> None:
    payload = {
        "action": "created",
        "installation": {"id": 5001},
        "repositories": [
            {"id": 8000, "full_name": "org/repo", "default_branch": "main", "language": "Python"},
        ],
    }
    r = _post(client, _configure_webhook_secret, "installation", payload)
    assert r.status_code == 202

    install = (
        await session.execute(select(Installation).where(Installation.github_installation_id == 5001))
    ).scalar_one()
    repo = (
        await session.execute(select(Repo).where(Repo.github_repo_id == 8000))
    ).scalar_one()
    config = (
        await session.execute(select(RepoConfig).where(RepoConfig.repo_id == repo.id))
    ).scalar_one()
    assert install.github_installation_id == 5001
    assert repo.full_name == "org/repo"
    assert repo.primary_language == "Python"
    assert config.enabled_steps_json["classify"] is True


@pytest.mark.asyncio
async def test_issues_opened_enqueues_and_respects_rate_limit(
    client, session, _configure_webhook_secret, _capture_enqueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed an installation so the payload has a known installation_id.
    install = Installation(github_installation_id=5002)
    session.add(install)
    await session.commit()

    payload = {
        "action": "opened",
        "installation": {"id": 5002},
        "issue": {"number": 42, "title": "boom"},
        "repository": {"id": 9000, "full_name": "org/repo"},
    }

    # First call under limit: enqueues.
    r = _post(client, _configure_webhook_secret, "issues", payload)
    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert len(_capture_enqueue) == 1

    # Force the next call over the limit.
    monkeypatch.setattr(rate_limit, "DEFAULT_LIMIT", 1)
    r2 = _post(client, _configure_webhook_secret, "issues", payload)
    assert r2.status_code == 202
    assert r2.json()["status"] == "rate_limited"
    assert len(_capture_enqueue) == 1  # did not enqueue the second


@pytest.mark.asyncio
async def test_installation_deleted_removes_row(client, session, _configure_webhook_secret) -> None:
    install = Installation(github_installation_id=5003)
    session.add(install)
    await session.commit()

    payload = {"action": "deleted", "installation": {"id": 5003}}
    r = _post(client, _configure_webhook_secret, "installation", payload)
    assert r.status_code == 202
    gone = (
        await session.execute(select(Installation).where(Installation.github_installation_id == 5003))
    ).scalar_one_or_none()
    assert gone is None
