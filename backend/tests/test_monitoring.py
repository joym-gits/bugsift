"""Tests for the generic-provider monitoring-event ingest endpoint.

Covers:
- Auth: missing/invalid token both 401, valid token 202.
- Rate limiting via the same two-tier Redis pattern as feedback ingest.
- Idempotency: repeat sends of the same (provider, external_event_id)
  bump occurrence_count instead of duplicating rows.
- Correlation: a matching suspected_files_json path on an existing
  card sets correlated_card_id.
- Token CRUD is repo-ownership-scoped; a revoked token stops working.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.api import monitoring as monitoring_api
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    Installation,
    MonitoringEvent,
    MonitoringIngestToken,
    Repo,
    TriageCard,
    User,
)
from bugsift.github import rate_limit


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


async def _seed_repo(session, user: User, *, name: str = "acme/web") -> Repo:
    install = Installation(github_installation_id=hash(name) & 0x7FFFFFFF, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=hash(name) & 0x7FFFFFF,
        full_name=name,
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


async def _seed_token(session, repo: Repo, *, token: str = "mit_test") -> MonitoringIngestToken:
    tok = MonitoringIngestToken(repo_id=repo.id, token=token)
    session.add(tok)
    await session.commit()
    await session.refresh(tok)
    return tok


def _payload(**overrides) -> dict:
    body = {
        "provider": "sentry",
        "external_event_id": "evt-1",
        "level": "error",
        "message": "NoneType has no attribute 'foo'",
        "file_paths": ["backend/app.py"],
        "occurrence_count": 1,
    }
    body.update(overrides)
    return body


def test_ingest_requires_token(client) -> None:
    r = client.post("/monitoring/ingest", json=_payload())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_token(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)
    await _seed_token(session, repo)
    r = client.post(
        "/monitoring/ingest",
        json=_payload(),
        headers={"X-Bugsift-Monitor-Token": "mit_wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingest_creates_event(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)

    r = client.post(
        "/monitoring/ingest",
        json=_payload(),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["provider"] == "sentry"
    assert body["occurrence_count"] == 1
    assert body["correlated_card_id"] is None


@pytest.mark.asyncio
async def test_ingest_correlates_matching_card(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)
    card = TriageCard(
        repo_id=repo.id,
        source="analysis",
        status="pending",
        suspected_files_json=[
            {"file_path": "backend/app.py", "line_range": "1-5", "rationale": "x"}
        ],
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)

    r = client.post(
        "/monitoring/ingest",
        json=_payload(file_paths=["backend/app.py"]),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )
    assert r.status_code == 202, r.text
    assert r.json()["correlated_card_id"] == card.id


@pytest.mark.asyncio
async def test_ingest_dedupes_by_external_event_id(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)

    first = client.post(
        "/monitoring/ingest",
        json=_payload(occurrence_count=1),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )
    second = client.post(
        "/monitoring/ingest",
        json=_payload(occurrence_count=3),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["occurrence_count"] == 4

    from sqlalchemy import select

    events = (
        (
            await session.execute(
                select(MonitoringEvent).where(MonitoringEvent.repo_id == repo.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


@pytest.mark.asyncio
async def test_ingest_rate_limited(client, session, logged_in, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)
    monkeypatch.setattr(monitoring_api, "INGEST_RATE_LIMIT_PER_MIN", 2)

    statuses = [
        client.post(
            "/monitoring/ingest",
            json=_payload(external_event_id=f"evt-{i}"),
            headers={"X-Bugsift-Monitor-Token": tok.token},
        ).status_code
        for i in range(4)
    ]
    assert statuses[:2] == [202, 202]
    assert 429 in statuses[2:]


@pytest.mark.asyncio
async def test_create_token_requires_ownership(client, session, logged_in) -> None:
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    theirs = await _seed_repo(session, stranger, name="someone/else")
    await session.commit()

    r = client.post(f"/monitoring/repos/{theirs.id}/tokens")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_and_revoke_token(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)

    created = client.post(f"/monitoring/repos/{repo.id}/tokens")
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    token_id = created.json()["id"]

    ingest_ok = client.post(
        "/monitoring/ingest",
        json=_payload(),
        headers={"X-Bugsift-Monitor-Token": token},
    )
    assert ingest_ok.status_code == 202

    revoked = client.delete(f"/monitoring/tokens/{token_id}")
    assert revoked.status_code == 204

    ingest_after_revoke = client.post(
        "/monitoring/ingest",
        json=_payload(external_event_id="evt-after-revoke"),
        headers={"X-Bugsift-Monitor-Token": token},
    )
    assert ingest_after_revoke.status_code == 401


@pytest.mark.asyncio
async def test_list_events_requires_ownership(client, session, logged_in) -> None:
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    theirs = await _seed_repo(session, stranger, name="someone/else2")
    await session.commit()

    r = client.get(f"/monitoring/events?repo_id={theirs.id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_events_returns_owned_repo_events(client, session, logged_in) -> None:
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)
    client.post(
        "/monitoring/ingest",
        json=_payload(),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )

    r = client.get(f"/monitoring/events?repo_id={repo.id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["provider"] == "sentry"
    assert body[0]["resolved_at"] is None


@pytest.mark.asyncio
async def test_skipping_correlated_card_resolves_event(client, session, logged_in) -> None:
    """Closes the analysis -> triage -> monitoring loop: once the card
    a monitoring event correlated to is skipped, the event should show
    up as resolved instead of looking permanently outstanding."""
    repo = await _seed_repo(session, logged_in)
    tok = await _seed_token(session, repo)
    card = TriageCard(
        repo_id=repo.id,
        source="analysis",
        status="pending",
        suspected_files_json=[
            {"file_path": "backend/app.py", "line_range": "1-5", "rationale": "x"}
        ],
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)

    ingested = client.post(
        "/monitoring/ingest",
        json=_payload(file_paths=["backend/app.py"]),
        headers={"X-Bugsift-Monitor-Token": tok.token},
    )
    assert ingested.json()["correlated_card_id"] == card.id
    assert ingested.json()["resolved_at"] is None

    skipped = client.post(f"/cards/{card.id}/skip")
    assert skipped.status_code == 200, skipped.text

    events = client.get(f"/monitoring/events?repo_id={repo.id}").json()
    assert events[0]["resolved_at"] is not None
    assert events[0]["resolution_status"] == "skipped"
