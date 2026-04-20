"""Tests for the weekly-digest computation + API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TriageCard,
    User,
)
from bugsift.feedback.digest import (
    _cluster_reports,
    compute_digest,
    current_weekly_window,
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


def _unit(dim: int, *nz: tuple[int, float]) -> list[float]:
    v = [0.0] * dim
    for pos, w in nz:
        v[pos] = w
    mag = sum(x * x for x in v) ** 0.5
    return [x / mag for x in v] if mag else v


def _report(
    *, app_id: int, body: str, vec: list[float] | None = None, card_id: int | None = None
) -> FeedbackReport:
    return FeedbackReport(
        app_id=app_id,
        body_text=body,
        content_hash=body[:40] or "x",
        embedding_384=vec,
        card_id=card_id,
    )


def test_cluster_groups_near_dups():
    reports = [
        _report(app_id=1, body="save is broken", vec=_unit(384, (0, 1.0))),
        _report(app_id=1, body="Save button does nothing", vec=_unit(384, (0, 0.99), (1, 0.1))),
        _report(app_id=1, body="totally unrelated", vec=_unit(384, (10, 1.0))),
        _report(app_id=1, body="profile save broken too", vec=_unit(384, (0, 1.0), (2, 0.05))),
    ]
    for i, r in enumerate(reports, start=1):
        r.id = i

    clusters = _cluster_reports(reports)
    # 3 similar reports should cluster; singleton gets dropped.
    assert len(clusters) == 1
    assert clusters[0].size() == 3


def test_cluster_drops_reports_without_embeddings():
    reports = [
        _report(app_id=1, body="no embedding", vec=None),
        _report(app_id=1, body="a", vec=_unit(384, (0, 1.0))),
        _report(app_id=1, body="b", vec=_unit(384, (0, 1.0))),
    ]
    for i, r in enumerate(reports, start=1):
        r.id = i
    clusters = _cluster_reports(reports)
    assert len(clusters) == 1
    assert clusters[0].size() == 2


def test_current_weekly_window_returns_monday_midnight():
    # Wednesday 2026-04-22 12:34 UTC
    now = datetime(2026, 4, 22, 12, 34, tzinfo=UTC)
    start, end = current_weekly_window(now)
    assert start == datetime(2026, 4, 20, 0, 0, tzinfo=UTC)  # Monday 04-20
    assert end - start == timedelta(days=7)


@pytest_asyncio.fixture
async def seeded_app(session, logged_in: User):
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
    await session.flush()
    app = FeedbackApp(
        user_id=logged_in.id,
        name="web",
        public_key="pk_web",
        default_repo_id=repo.id,
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return app, repo


@pytest.mark.asyncio
async def test_compute_digest_counts_and_clusters(session, seeded_app):
    app, repo = seeded_app
    now = datetime.now(UTC)
    start, end = current_weekly_window(now)

    # 3 "save" reports this week, linked to a card, plus 1 unrelated
    card = TriageCard(
        repo_id=repo.id,
        source="feedback",
        issue_number=None,
        feedback_report_ids_json=[],
        status="pending",
        classification="bug",
        severity="high",
        suspected_files_json=[
            {"file_path": "save.py", "line_range": "1-10", "rationale": "x"}
        ],
    )
    session.add(card)
    await session.flush()

    near_vec = _unit(384, (0, 1.0))
    for i in range(3):
        r = FeedbackReport(
            app_id=app.id,
            body_text=f"save is broken {i}",
            content_hash=f"h{i}",
            embedding_384=near_vec,
            card_id=card.id,
            created_at=now - timedelta(hours=1 + i),
        )
        session.add(r)
    # Noise: an unrelated report, different embedding, no card.
    noise = FeedbackReport(
        app_id=app.id,
        body_text="totally different thing",
        content_hash="noise",
        embedding_384=_unit(384, (10, 1.0)),
        created_at=now - timedelta(hours=4),
    )
    session.add(noise)
    # Previous-week report to exercise trend math.
    prev = FeedbackReport(
        app_id=app.id,
        body_text="last week",
        content_hash="prev",
        embedding_384=_unit(384, (5, 1.0)),
        created_at=start - timedelta(hours=1),
    )
    session.add(prev)
    await session.commit()

    result = await compute_digest(
        session, app=app, period_start=start, period_end=end
    )
    assert result.report_count == 4  # 3 save + noise, prev is last week
    assert result.previous_report_count == 1
    assert len(result.clusters) == 1  # singleton noise filtered out
    assert result.clusters[0]["size"] == 3
    # Top files come from the cluster's card_id
    assert result.top_files == [{"file_path": "save.py", "card_count": 1}]
    assert result.severity_breakdown == {"high": 1}


@pytest.mark.asyncio
async def test_digest_endpoint_upserts_and_returns(client, seeded_app, session):
    app, _repo = seeded_app
    # Pre-seed a single recent report so the endpoint has something to count.
    now = datetime.now(UTC)
    session.add(
        FeedbackReport(
            app_id=app.id,
            body_text="hi",
            content_hash="x",
            embedding_384=None,
            created_at=now,
        )
    )
    await session.commit()

    r1 = client.post(f"/feedback/apps/{app.id}/digests/current")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["app_id"] == app.id
    assert body1["report_count"] == 1

    # Second call upserts (same period_start key), doesn't create a new row.
    r2 = client.post(f"/feedback/apps/{app.id}/digests/current")
    assert r2.status_code == 200
    r_list = client.get(f"/feedback/apps/{app.id}/digests")
    assert len(r_list.json()) == 1


def test_compute_rejects_other_users_app(client, session):
    import asyncio

    async def _seed() -> int:
        other = User(github_id=99, github_login="stranger", email=None)
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
    # No logged_in override here — request will 404.
    r = client.post(f"/feedback/apps/{other_id}/digests/current")
    assert r.status_code in (401, 404)
