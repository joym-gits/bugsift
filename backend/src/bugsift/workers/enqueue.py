"""Thin helpers that wrap the Redis/RQ enqueue calls.

Centralised so api/webhooks.py and api/cards.py (retry) both enqueue the
same way without duplicating the Redis wiring.
"""

from __future__ import annotations

from typing import Any

from redis import Redis
from rq import Queue

from bugsift.config import get_settings
from bugsift.workers import indexing as indexing_jobs
from bugsift.workers import triage as triage_jobs


def _queue(name: str) -> Queue:
    connection = Redis.from_url(get_settings().redis_url)
    return Queue(name, connection=connection)


def enqueue_triage(payload: dict[str, Any]) -> None:
    _queue("triage").enqueue(triage_jobs.process_issue_opened, payload)


def enqueue_index_repo(repo_id: int) -> None:
    _queue("indexing").enqueue(indexing_jobs.index_repo, repo_id)


def enqueue_index_repo_delta(
    repo_id: int, *, added: list[str], modified: list[str], removed: list[str]
) -> None:
    _queue("indexing").enqueue(
        indexing_jobs.index_repo_delta,
        repo_id,
        added=added,
        modified=modified,
        removed=removed,
    )


def enqueue_embed_issue(
    repo_id: int, issue_number: int, title: str, body: str
) -> None:
    _queue("indexing").enqueue(indexing_jobs.embed_issue, repo_id, issue_number, title, body)
