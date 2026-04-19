from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from bugsift.api import webhooks as webhook_route
from bugsift.config import get_settings
from bugsift.db.models import Installation, PushEvent, Repo, RepoConfig
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
    monkeypatch.setattr(webhook_route, "_enqueue_backfill_open_issues", lambda *a, **kw: None)


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
async def test_installation_created_enqueues_backfill(
    client, session, _configure_webhook_secret, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[int] = []
    monkeypatch.setattr(
        webhook_route, "_enqueue_backfill_open_issues", lambda repo_id: captured.append(repo_id)
    )

    payload = {
        "action": "created",
        "installation": {"id": 5010},
        "repositories": [
            {"id": 8100, "full_name": "org/repoA", "default_branch": "main"},
            {"id": 8101, "full_name": "org/repoB", "default_branch": "main"},
        ],
    }
    r = _post(client, _configure_webhook_secret, "installation", payload)
    assert r.status_code == 202

    repos = (
        await session.execute(select(Repo).where(Repo.github_repo_id.in_([8100, 8101])))
    ).scalars().all()
    assert {r.full_name for r in repos} == {"org/repoA", "org/repoB"}
    assert sorted(captured) == sorted(r.id for r in repos)


@pytest.mark.asyncio
async def test_installation_repositories_added_enqueues_backfill(
    client, session, _configure_webhook_secret, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = Installation(github_installation_id=5011)
    session.add(install)
    await session.commit()

    captured: list[int] = []
    monkeypatch.setattr(
        webhook_route, "_enqueue_backfill_open_issues", lambda repo_id: captured.append(repo_id)
    )

    payload = {
        "action": "added",
        "installation": {"id": 5011},
        "repositories_added": [
            {"id": 8200, "full_name": "org/newrepo", "default_branch": "main"},
        ],
    }
    r = _post(client, _configure_webhook_secret, "installation_repositories", payload)
    assert r.status_code == 202

    repo = (
        await session.execute(select(Repo).where(Repo.github_repo_id == 8200))
    ).scalar_one()
    assert captured == [repo.id]


@pytest.mark.asyncio
async def test_push_persists_push_events(
    client, session, _configure_webhook_secret
) -> None:
    install = Installation(github_installation_id=5020)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=9100,
        full_name="org/widget",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.commit()

    payload = {
        "ref": "refs/heads/main",
        "repository": {"id": 9100, "default_branch": "main"},
        "pusher": {"name": "alice"},
        "commits": [
            {
                "id": "a" * 40,
                "message": "fix: save handler (#77)",
                "timestamp": "2026-04-19T10:00:00Z",
                "author": {"name": "Alice", "username": "alice"},
                "added": [],
                "modified": ["app/save.py"],
                "removed": [],
            },
            {
                "id": "b" * 40,
                "message": "chore: rename util\n\nMerge pull request #78",
                "timestamp": "2026-04-19T11:00:00Z",
                "author": {"name": "Bob", "username": "bob"},
                "added": ["app/newutil.py"],
                "modified": [],
                "removed": [],
            },
        ],
    }

    r = _post(client, _configure_webhook_secret, "push", payload)
    assert r.status_code == 202

    rows = (
        await session.execute(select(PushEvent).where(PushEvent.repo_id == repo.id))
    ).scalars().all()
    assert len(rows) == 2
    by_sha = {row.commit_sha: row for row in rows}
    first = by_sha["a" * 40]
    assert first.pr_number == 77
    assert first.touched_paths_json == ["app/save.py"]
    assert first.author_login == "alice"
    assert first.ref == "refs/heads/main"
    second = by_sha["b" * 40]
    assert second.pr_number == 78
    assert second.touched_paths_json == ["app/newutil.py"]


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
