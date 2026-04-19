"""Tests for the regression correlator.

Covers:
- Overlap math: pushes that touched a suspected file surface; pushes
  that didn't stay invisible.
- Time-window guard: a push older than the window is ignored even if
  its files match.
- Pushes more recent than the report's reference time are not counted
  (they can't have caused a bug reported earlier).
- The orchestrator step is a no-op when ``suspected_files`` is empty.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bugsift.agent.state import SuspectedFile, TriageState
from bugsift.agent.steps import regression as regression_step
from bugsift.db.models import Installation, PushEvent, Repo, User
from bugsift.regression.correlator import find_regression_suspects


async def _seed_repo(session) -> Repo:
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
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


async def _push(
    session,
    repo: Repo,
    *,
    sha: str,
    pushed_at: datetime,
    paths: list[str],
    message: str = "",
    pr: int | None = None,
) -> None:
    session.add(
        PushEvent(
            repo_id=repo.id,
            commit_sha=sha,
            message_first_line=message,
            author_name="dev",
            pushed_at=pushed_at,
            ref="refs/heads/main",
            touched_paths_json=paths,
            pr_number=pr,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_overlaps_surface_matching_pushes(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    await _push(
        session,
        repo,
        sha="a" * 40,
        pushed_at=now - timedelta(hours=2),
        paths=["app/profile/save.py", "README.md"],
        message="fix: save handler (#42)",
        pr=42,
    )

    suspects = await find_regression_suspects(
        session,
        repo_id=repo.id,
        suspected_paths=["app/profile/save.py"],
        reference_time=now,
    )
    assert len(suspects) == 1
    assert suspects[0].short_sha == "a" * 7
    assert suspects[0].pr_number == 42
    assert suspects[0].overlapping_paths == ["app/profile/save.py"]


@pytest.mark.asyncio
async def test_pushes_without_overlap_are_ignored(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    await _push(
        session,
        repo,
        sha="b" * 40,
        pushed_at=now - timedelta(hours=1),
        paths=["docs/readme.md"],
    )
    suspects = await find_regression_suspects(
        session,
        repo_id=repo.id,
        suspected_paths=["app/profile/save.py"],
        reference_time=now,
    )
    assert suspects == []


@pytest.mark.asyncio
async def test_pushes_older_than_window_are_ignored(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    await _push(
        session,
        repo,
        sha="c" * 40,
        pushed_at=now - timedelta(days=30),
        paths=["app/save.py"],
    )
    suspects = await find_regression_suspects(
        session,
        repo_id=repo.id,
        suspected_paths=["app/save.py"],
        reference_time=now,
        window_days=14,
    )
    assert suspects == []


@pytest.mark.asyncio
async def test_pushes_after_report_time_are_ignored(session):
    """A commit that lands *after* the bug was reported can't have caused it."""
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    await _push(
        session,
        repo,
        sha="d" * 40,
        pushed_at=now + timedelta(hours=2),
        paths=["app/save.py"],
    )
    suspects = await find_regression_suspects(
        session,
        repo_id=repo.id,
        suspected_paths=["app/save.py"],
        reference_time=now,
    )
    assert suspects == []


@pytest.mark.asyncio
async def test_limit_is_respected_and_sorted_newest_first(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    for i in range(5):
        await _push(
            session,
            repo,
            sha=f"{i}" * 40,
            pushed_at=now - timedelta(hours=i + 1),
            paths=["app/save.py"],
            message=f"change #{i}",
        )
    suspects = await find_regression_suspects(
        session,
        repo_id=repo.id,
        suspected_paths=["app/save.py"],
        reference_time=now,
        limit=3,
    )
    assert [s.short_sha for s in suspects] == [f"{i}" * 7 for i in range(3)]


@pytest.mark.asyncio
async def test_step_is_noop_without_suspected_files(session):
    state = TriageState(
        repo_id=1,
        repo_full_name="acme/web",
        issue_number=1,
        issue_title="x",
        issue_body="x",
    )
    out = await regression_step.run(state, session=session)
    assert out.regression_suspects == []


@pytest.mark.asyncio
async def test_step_populates_state_from_matching_push(session):
    repo = await _seed_repo(session)
    now = datetime.now(UTC)
    await _push(
        session,
        repo,
        sha="e" * 40,
        pushed_at=now - timedelta(hours=3),
        paths=["app/save.py"],
        message="regression: null deref (#77)",
        pr=77,
    )
    state = TriageState(
        repo_id=repo.id,
        repo_full_name=repo.full_name,
        issue_number=1,
        issue_title="x",
        issue_body="x",
        suspected_files=[
            SuspectedFile(
                file_path="app/save.py",
                line_range="1-5",
                rationale="mentioned",
            )
        ],
    )
    out = await regression_step.run(state, session=session, reference_time=now)
    assert len(out.regression_suspects) == 1
    record = out.regression_suspects[0]
    assert record.pr_number == 77
    assert "app/save.py" in record.overlapping_paths
    # pushed_at is persisted as an iso string so it round-trips through JSON.
    assert record.pushed_at_iso.startswith("20")
