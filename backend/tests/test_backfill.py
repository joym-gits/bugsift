"""Tests for the open-issue backfill worker.

The worker pulls GitHub's per-repo issues list and shoves each issue into
the triage queue as if it were a fresh ``issues.opened`` webhook. We stub
the network call and the enqueue function so the test covers shape +
filtering logic without Redis or GitHub.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from bugsift.db.models import Installation, Repo
from bugsift.workers import backfill as backfill_mod


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "ok"

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(self, pages: list[list[dict]]) -> None:
        self._pages = pages
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers, params, timeout):  # noqa: D401
        self.calls.append({"url": url, "params": dict(params)})
        idx = params.get("page", 1) - 1
        if idx >= len(self._pages):
            return _FakeResponse(200, [])
        return _FakeResponse(200, self._pages[idx])


@pytest.mark.asyncio
async def test_backfill_enqueues_each_open_issue_and_skips_prs(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed the minimum set of rows the backfill worker reads.
    install = Installation(github_installation_id=77)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=123,
        full_name="org/repo",
        default_branch="main",
        indexing_status="pending",
    )
    session.add(repo)
    await session.commit()
    repo_id = repo.id

    # Point the worker's SessionLocal at the test session's engine so it
    # sees the rows we just seeded. Simpler than wiring a fresh fixture.
    from bugsift.db import session as db_session

    monkeypatch.setattr(
        db_session, "SessionLocal", lambda: _UseExisting(session)
    )
    monkeypatch.setattr(
        backfill_mod, "SessionLocal", lambda: _UseExisting(session)
    )

    async def _fake_token(installation_id, *, app_id, private_key_pem):
        return "fake-token"

    monkeypatch.setattr(backfill_mod.gh_app, "get_installation_token", _fake_token)

    async def _fake_load_cfg(_session):
        class _Cfg:
            app_id = 1
            private_key_pem = "pem"
        return _Cfg()

    monkeypatch.setattr(backfill_mod.app_config, "load_app_config", _fake_load_cfg)

    pages = [
        [
            {"number": 1, "title": "first", "body": "b1"},
            {"number": 2, "title": "a PR", "body": "", "pull_request": {}},
            {"number": 3, "title": "third", "body": "b3"},
        ],
    ]
    fake_client = _FakeClient(pages)
    monkeypatch.setattr(backfill_mod.httpx, "AsyncClient", lambda: fake_client)

    enqueued: list[dict] = []
    monkeypatch.setattr(
        backfill_mod.enqueue_jobs,
        "enqueue_triage",
        lambda payload: enqueued.append(payload),
    )

    await backfill_mod._backfill_open_issues(repo_id)

    # PR filtered out; two triage payloads queued.
    assert [p["issue"]["number"] for p in enqueued] == [1, 3]
    # Payload shape matches what the triage worker expects.
    sample = enqueued[0]
    assert sample["action"] == "opened"
    assert sample["repository"]["id"] == 123
    assert sample["repository"]["full_name"] == "org/repo"
    assert sample["installation"]["id"] == 77


class _UseExisting:
    """Session context that yields an existing AsyncSession without closing."""

    def __init__(self, sess):
        self._sess = sess

    async def __aenter__(self):
        return self._sess

    async def __aexit__(self, exc_type, exc, tb):
        # Intentionally do not close — the test fixture owns the session.
        return False
