"""Tests for CODEOWNERS parsing, matching, and orchestrator assignment."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.agent.state import SuspectedFile, TriageState
from bugsift.agent.steps import assignment as assignment_step
from bugsift.db.models import Installation, Repo, User
from bugsift.github import rate_limit
from bugsift.github.codeowners import owners_for_file, owners_for_files, parse


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


# --- parser ---


def test_parse_strips_comments_and_blank_lines():
    text = """
    # header
    *                @default-owner

    # auth section
    app/auth/*       @alice @bob
    """
    rules = parse(text)
    assert [r.pattern for r in rules] == ["*", "app/auth/*"]
    assert rules[1].owners == ["@alice", "@bob"]


def test_parse_skips_rules_without_owners():
    text = "app/**\n"  # no owners
    assert parse(text) == []


# --- matcher ---


def test_last_match_wins():
    rules = parse(
        """
        *                @default
        app/**           @app-team-owner
        app/auth/*       @alice
        """
    )
    # More-specific rule (listed later) should win.
    assert owners_for_file(rules, "app/auth/login.py") == ["alice"]
    # Outside auth → app-team.
    assert owners_for_file(rules, "app/profile/save.py") == ["app-team-owner"]


def test_no_match_returns_empty():
    rules = parse("docs/**   @docs-owner\n")
    assert owners_for_file(rules, "src/core.py") == []


def test_team_owners_are_dropped():
    rules = parse("app/**   @myorg/backend-team @alice\n")
    # Team stays filtered; user survives.
    assert owners_for_file(rules, "app/save.py") == ["alice"]


def test_double_star_matches_recursively():
    rules = parse("**/CHANGELOG.md   @docs\n")
    assert owners_for_file(rules, "CHANGELOG.md") == ["docs"]
    assert owners_for_file(rules, "packages/ui/CHANGELOG.md") == ["docs"]


def test_anchored_pattern_requires_repo_root():
    rules = parse("/docs/*   @docs\n")
    assert owners_for_file(rules, "docs/guide.md") == ["docs"]
    # Not at root → no match.
    assert owners_for_file(rules, "app/docs/internal.md") == []


def test_trailing_slash_matches_directory_and_contents():
    rules = parse("app/admin/   @admin-team-user\n")
    assert owners_for_file(rules, "app/admin/page.py") == ["admin-team-user"]


def test_owners_for_files_dedupes_preserving_order():
    rules = parse(
        """
        app/auth/*   @alice
        app/profile/*  @alice @bob
        """
    )
    result = owners_for_files(
        rules, ["app/auth/login.py", "app/profile/save.py", "app/auth/logout.py"]
    )
    # alice shows up first from login.py; bob on the second file.
    assert result == ["alice", "bob"]


# --- orchestrator step ---


async def _seed_repo(session, codeowners: str | None) -> Repo:
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
        codeowners_text=codeowners,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


@pytest.mark.asyncio
async def test_step_noop_without_suspected_files(session):
    repo = await _seed_repo(session, "* @alice\n")
    state = TriageState(
        repo_id=repo.id,
        repo_full_name="acme/web",
        issue_number=1,
        issue_title="x",
        issue_body="x",
    )
    out = await assignment_step.run(state, session=session)
    assert out.suggested_assignees == []


@pytest.mark.asyncio
async def test_step_noop_without_codeowners(session):
    repo = await _seed_repo(session, None)
    state = TriageState(
        repo_id=repo.id,
        repo_full_name="acme/web",
        issue_number=1,
        issue_title="x",
        issue_body="x",
        suspected_files=[
            SuspectedFile(file_path="app/save.py", line_range="1-10", rationale="x")
        ],
    )
    out = await assignment_step.run(state, session=session)
    assert out.suggested_assignees == []


@pytest.mark.asyncio
async def test_step_populates_assignees(session):
    repo = await _seed_repo(
        session,
        """
        *                @default
        app/profile/*    @alice
        """,
    )
    state = TriageState(
        repo_id=repo.id,
        repo_full_name="acme/web",
        issue_number=1,
        issue_title="x",
        issue_body="x",
        suspected_files=[
            SuspectedFile(
                file_path="app/profile/save.py",
                line_range="1-10",
                rationale="the crash site",
            )
        ],
    )
    out = await assignment_step.run(state, session=session)
    assert out.suggested_assignees == ["alice"]
