"""Thin helpers that wrap the Redis/RQ enqueue calls.

Centralised so api/webhooks.py and api/cards.py (retry) both enqueue the
same way without duplicating the Redis wiring.
"""

from __future__ import annotations

from typing import Any

from redis import Redis
from rq import Queue

from bugsift.config import get_settings
from bugsift.workers import analyze as analyze_jobs
from bugsift.workers import backfill as backfill_jobs
from bugsift.workers import codeowners as codeowners_jobs
from bugsift.workers import feedback_triage as feedback_triage_jobs
from bugsift.workers import indexing as indexing_jobs
from bugsift.workers import slack as slack_jobs
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


def enqueue_backfill_open_issues(repo_id: int) -> None:
    _queue("indexing").enqueue(backfill_jobs.backfill_open_issues, repo_id)


def enqueue_feedback_triage(report_id: int) -> None:
    """Kick a widget-sourced feedback report through the triage pipeline.
    Same ``triage`` queue as GitHub issues so the worker sees one stream."""
    _queue("triage").enqueue(feedback_triage_jobs.process_feedback_report, report_id)


def enqueue_analyze_feedback_app(feedback_app_id: int) -> None:
    """Kick a full repo analysis for the repo behind a feedback app.
    Uses the ``indexing`` queue — the job is cpu/IO-heavy and we don't
    want it blocking triage throughput."""
    _queue("indexing").enqueue(
        analyze_jobs.analyze_for_app, feedback_app_id, job_timeout=1800
    )


def enqueue_refresh_codeowners(repo_id: int) -> None:
    """Fetch + cache CODEOWNERS on the repo row. Cheap; run after
    install / hydrate / push to the default branch."""
    _queue("indexing").enqueue(codeowners_jobs.refresh_codeowners, repo_id)


def enqueue_slack_notification(card_id: int, event: str) -> None:
    """Fan-out a card event to every matching Slack destination.

    Goes through the ``default`` queue so slow Slack calls don't back
    up triage. The worker itself decides which destinations to hit."""
    _queue("default").enqueue(slack_jobs.notify_card_event, card_id, event)
