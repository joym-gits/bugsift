"""Tests for the rule-based severity assignment + API filter."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.agent.severity import compute_severity
from bugsift.agent.state import RegressionSuspectRecord, TriageState
from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import Installation, Repo, TriageCard, User
from bugsift.github import rate_limit


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


def _state(
    classification: str | None = "bug",
    *,
    reproduced: bool = False,
    regression: bool = False,
) -> TriageState:
    state = TriageState(
        repo_id=1,
        repo_full_name="acme/web",
        issue_number=1,
        issue_title="x",
        issue_body="x",
        classification=classification,
    )
    if reproduced:
        state.reproduction_verdict = "reproduced"
    if regression:
        state.regression_suspects = [
            RegressionSuspectRecord(
                commit_sha="a" * 40,
                short_sha="a" * 7,
                message_first_line="x",
                author_name=None,
                author_login=None,
                pushed_at_iso="2026-04-20T00:00:00+00:00",
                pr_number=None,
                ref=None,
                overlapping_paths=["x.py"],
            )
        ]
    return state


def test_spam_returns_none():
    assert compute_severity(_state("spam")) is None


def test_unclassified_returns_none():
    assert compute_severity(_state(None)) is None


def test_bug_base_medium():
    assert compute_severity(_state("bug")) == "medium"


def test_needs_info_base_low():
    assert compute_severity(_state("needs_info")) == "low"


def test_reproduced_bumps_bug_to_high():
    assert compute_severity(_state("bug", reproduced=True)) == "high"


def test_regression_bumps_bug_to_high():
    assert compute_severity(_state("bug", regression=True)) == "high"


def test_reproduced_and_regression_bumps_to_blocker():
    assert (
        compute_severity(_state("bug", reproduced=True, regression=True)) == "blocker"
    )


def test_many_reports_bumps_up():
    assert compute_severity(_state("bug"), feedback_report_count=10) == "high"


def test_everything_still_caps_at_blocker():
    assert (
        compute_severity(
            _state("bug", reproduced=True, regression=True), feedback_report_count=20
        )
        == "blocker"
    )


def test_low_with_all_signals_caps_at_blocker():
    assert (
        compute_severity(
            _state("needs_info", reproduced=True, regression=True),
            feedback_report_count=20,
        )
        == "blocker"
    )


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


@pytest.mark.asyncio
async def test_cards_list_filters_by_severity(client, session, logged_in):
    install = Installation(github_installation_id=1, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    for sev, issue_no in [("blocker", 1), ("medium", 2), ("low", 3)]:
        session.add(
            TriageCard(
                repo_id=repo.id,
                issue_number=issue_no,
                source="github",
                status="pending",
                classification="bug",
                severity=sev,
            )
        )
    await session.commit()

    r = client.get("/cards?severity=blocker")
    assert r.status_code == 200
    assert [c["severity"] for c in r.json()] == ["blocker"]

    r = client.get("/cards?severity=medium")
    assert [c["severity"] for c in r.json()] == ["medium"]


@pytest.mark.asyncio
async def test_cards_response_carries_severity(client, session, logged_in):
    install = Installation(github_installation_id=2, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=2,
        full_name="acme/api",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.flush()
    session.add(
        TriageCard(
            repo_id=repo.id,
            issue_number=7,
            source="github",
            status="pending",
            classification="bug",
            severity="high",
        )
    )
    await session.commit()

    r = client.get("/cards")
    assert r.status_code == 200
    assert r.json()[0]["severity"] == "high"
