from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import FeedbackReport, Installation, Repo, TriageCard, User
from bugsift.feedback import issue_body as feedback_issue_body
from bugsift.github import config as app_config
from bugsift.github.client import GithubClient
from bugsift.workers import enqueue as enqueue_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cards", tags=["cards"])


def get_github_client_factory():
    """Return a callable ``(installation_id) -> GithubClient``.

    Exposed as a FastAPI dependency so tests can override it with a fake.
    """
    return GithubClient


class SuspectedFileOut(BaseModel):
    file_path: str
    line_range: str
    rationale: str


class DuplicateOut(BaseModel):
    issue_number: int
    rationale: str
    confidence: float


class CardResponse(BaseModel):
    id: int
    repo_full_name: str
    repo_default_branch: str | None = None
    # For feedback-sourced cards, ``issue_number`` is null until approve
    # opens the GitHub issue (at which point ``github_issue_number`` fills in).
    issue_number: int | None = None
    source: str = "github"
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    feedback_report_count: int = 0
    status: str
    classification: str | None
    confidence: float | None = None
    rationale: str | None = None
    draft_comment: str | None = None
    proposed_action: str | None = None
    proposed_labels: list[str] | None = None
    suspected_files: list[SuspectedFileOut] | None = None
    duplicates: list[DuplicateOut] | None = None
    reproduction_verdict: str | None = None
    reproduction_log: str | None = None
    budget_limited: bool = False
    final_comment: str | None = None
    created_at: datetime


class EditBody(BaseModel):
    draft_comment: str


class ApproveBody(BaseModel):
    """Optional body on approve. Only ``admin_note`` is read today (for
    feedback-sourced cards it gets rendered into the new GitHub issue);
    new fields can be added without breaking clients that POST an empty
    body."""

    admin_note: str | None = Field(default=None, max_length=8000)


@router.get("", response_model=list[CardResponse])
async def list_cards(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 50,
    status: str | None = None,
    classification: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
) -> list[CardResponse]:
    """List triage cards the current user owns, newest first.

    All filters are optional; the dashboard calls without any (so it sees the
    whole recent queue) and the history page passes them to narrow the view.
    """
    repo = aliased(Repo)
    install = aliased(Installation)
    stmt = (
        select(TriageCard, repo.full_name, repo.default_branch)
        .join(repo, TriageCard.repo_id == repo.id)
        .join(install, repo.installation_id == install.id)
        .where(install.user_id == user.id)
    )
    if status:
        stmt = stmt.where(TriageCard.status == status)
    if classification:
        stmt = stmt.where(TriageCard.classification == classification)
    if verdict:
        stmt = stmt.where(TriageCard.reproduction_verdict == verdict)
    if source:
        stmt = stmt.where(TriageCard.source == source)
    stmt = stmt.order_by(TriageCard.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [_card_response(card, full_name, branch) for card, full_name, branch in rows]


class FeedbackReportOut(BaseModel):
    id: int
    body_text: str
    url: str | None
    user_agent: str | None
    app_version: str | None
    console_log: str | None
    reporter_hash: str | None
    created_at: datetime


@router.get("/{card_id}/reports", response_model=list[FeedbackReportOut])
async def list_card_reports(
    card_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[FeedbackReportOut]:
    """Underlying widget reports for a feedback-sourced card.

    Returns an empty list for ``source='github'`` cards (no reports)
    rather than 404ing, so the dashboard can unconditionally fetch."""
    card, _, _ = await _get_owned_card(session, user, card_id)
    if card.source != "feedback":
        return []
    ids = card.feedback_report_ids_json or []
    if not isinstance(ids, list) or not ids:
        return []
    rows = (
        await session.execute(
            select(FeedbackReport)
            .where(FeedbackReport.id.in_([int(i) for i in ids]))
            .order_by(FeedbackReport.created_at.asc())
        )
    ).scalars().all()
    return [
        FeedbackReportOut(
            id=r.id,
            body_text=r.body_text,
            url=r.url,
            user_agent=r.user_agent,
            app_version=r.app_version,
            console_log=r.console_log,
            reporter_hash=r.reporter_hash,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def _get_owned_card(session: AsyncSession, user: User, card_id: int) -> tuple[TriageCard, Repo, Installation]:
    stmt = (
        select(TriageCard, Repo, Installation)
        .join(Repo, TriageCard.repo_id == Repo.id)
        .join(Installation, Repo.installation_id == Installation.id)
        .where(TriageCard.id == card_id, Installation.user_id == user.id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="card not found")
    return row[0], row[1], row[2]


@router.patch("/{card_id}", response_model=CardResponse)
async def edit_draft(
    card_id: int,
    body: EditBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CardResponse:
    card, repo, _ = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    card.draft_comment = body.draft_comment
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


@router.post("/{card_id}/rerun", status_code=202)
async def rerun_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Re-enqueue triage for a still-pending card using its stored webhook
    payload. Useful after the user adds/fixes an LLM key — cards stuck at
    "No LLM key configured" become live again without a new GitHub event.
    """
    card, _, _ = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    payload = card.raw_payload_json
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="card has no stored webhook payload; cannot rerun",
        )
    # Drop the old row — the worker will create a fresh one from the payload.
    # (uq_repo_issue would block the insert otherwise.)
    await session.delete(card)
    await session.commit()
    enqueue_jobs.enqueue_triage(payload)
    logger.info("rerun queued for card_id=%s by user_id=%s", card_id, user.id)
    return {"status": "queued"}


@router.post("/{card_id}/skip", response_model=CardResponse)
async def skip_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CardResponse:
    card, repo, _ = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    card.status = "skipped"
    card.decided_at = datetime.now(UTC)
    card.decided_by_user_id = user.id
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


@router.post("/{card_id}/approve", response_model=CardResponse)
async def approve_card(
    card_id: int,
    body: ApproveBody | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    github_client_factory = Depends(get_github_client_factory),
) -> CardResponse:
    card, repo, install = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")

    cfg = await app_config.load_app_config(session)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App is not configured — finish onboarding first",
        )
    client = github_client_factory(
        install.github_installation_id,
        app_id=cfg.app_id,
        private_key_pem=cfg.private_key_pem,
    )

    if card.source == "feedback":
        await _approve_feedback_card(
            session=session,
            card=card,
            repo=repo,
            user=user,
            client=client,
            admin_note=(body.admin_note if body else None),
        )
    else:
        await _approve_github_card(card=card, repo=repo, client=client)
        card.final_comment = card.draft_comment

    card.status = "posted"
    card.decided_at = datetime.now(UTC)
    card.decided_by_user_id = user.id
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


async def _approve_github_card(*, card: TriageCard, repo: Repo, client) -> None:
    """Classic flow: comment on the existing GitHub issue, optionally
    apply labels, optionally close."""
    if not card.draft_comment:
        raise HTTPException(status_code=400, detail="card has no draft comment to post")
    try:
        await client.post_issue_comment(repo.full_name, card.issue_number, card.draft_comment)
    except Exception as e:
        logger.exception("failed to post comment card_id=%s", card.id)
        raise HTTPException(status_code=502, detail=f"failed to post comment: {e}") from e

    labels = card.proposed_labels_json or []
    if card.proposed_action == "comment_and_label" and labels:
        try:
            await client.add_labels(repo.full_name, card.issue_number, labels)
        except Exception:
            logger.warning("labels apply failed card_id=%s; continuing", card.id)

    if card.proposed_action == "comment_and_close":
        try:
            await client.close_issue(repo.full_name, card.issue_number)
        except Exception:
            logger.warning("close failed card_id=%s; continuing", card.id)


async def _approve_feedback_card(
    *,
    session: AsyncSession,
    card: TriageCard,
    repo: Repo,
    user: User,
    client,
    admin_note: str | None = None,
) -> None:
    """Open a brand-new GitHub issue for a widget-sourced feedback card,
    then stamp the card with the resulting issue number so the dashboard
    can link out to it.
    """
    report_rows = await _load_feedback_reports_for_card(session, card)
    if not report_rows:
        raise HTTPException(
            status_code=400,
            detail="feedback card has no reports to file",
        )

    snippets = [
        feedback_issue_body.ReportSnippet(
            body_text=r.body_text,
            url=r.url,
            app_version=r.app_version,
            created_at_iso=r.created_at.isoformat(),
        )
        for r in report_rows
    ]
    title, body = feedback_issue_body.build_issue(
        reports=snippets,
        rationale=card.rationale,
        classification=card.classification,
        confidence=float(card.confidence) if card.confidence is not None else None,
        suspected_files=feedback_issue_body.snippets_from_suspected_json(
            card.suspected_files_json
        ),
        reproduction_verdict=card.reproduction_verdict,
        reproduction_log=card.reproduction_log,
        admin_note=admin_note,
    )

    labels: list[str] = []
    if card.proposed_labels_json and isinstance(card.proposed_labels_json, list):
        labels = [str(x) for x in card.proposed_labels_json if str(x).strip()]

    try:
        created = await client.create_issue(
            repo.full_name, title=title, body=body, labels=labels or None
        )
    except Exception as e:
        logger.exception("failed to create GitHub issue card_id=%s", card.id)
        raise HTTPException(
            status_code=502, detail=f"failed to create GitHub issue: {e}"
        ) from e

    github_number = created.get("number")
    if isinstance(github_number, int):
        card.github_issue_number = github_number
    card.final_comment = body
    logger.info(
        "feedback card_id=%s opened github issue %s#%s",
        card.id,
        repo.full_name,
        github_number,
    )


async def _load_feedback_reports_for_card(
    session: AsyncSession, card: TriageCard
) -> list[FeedbackReport]:
    ids = card.feedback_report_ids_json or []
    if not isinstance(ids, list) or not ids:
        return []
    rows = (
        await session.execute(
            select(FeedbackReport)
            .where(FeedbackReport.id.in_([int(i) for i in ids]))
            .order_by(FeedbackReport.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


def _card_response(
    card: TriageCard, repo_full_name: str, repo_default_branch: str | None = None
) -> CardResponse:
    suspected = None
    if card.suspected_files_json:
        suspected = [
            SuspectedFileOut(
                file_path=str(item.get("file_path", "")),
                line_range=str(item.get("line_range", "")),
                rationale=str(item.get("rationale", "")),
            )
            for item in card.suspected_files_json
        ]
    duplicates = None
    if card.duplicates_json:
        duplicates = [
            DuplicateOut(
                issue_number=int(item.get("issue_number", 0)),
                rationale=str(item.get("rationale", "")),
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in card.duplicates_json
        ]
    feedback_ids = card.feedback_report_ids_json or []
    if not isinstance(feedback_ids, list):
        feedback_ids = []
    issue_url: str | None = None
    # Both github- and feedback-sourced cards can link to a GitHub
    # issue. For ``source='github'`` the number lives on ``issue_number``;
    # for approved feedback cards it's on ``github_issue_number``.
    linked_number = card.github_issue_number or (
        card.issue_number if (card.source or "github") == "github" else None
    )
    if linked_number:
        issue_url = f"https://github.com/{repo_full_name}/issues/{linked_number}"
    return CardResponse(
        id=card.id,
        repo_full_name=repo_full_name,
        repo_default_branch=repo_default_branch,
        issue_number=card.issue_number,
        source=card.source or "github",
        github_issue_number=card.github_issue_number,
        github_issue_url=issue_url,
        feedback_report_count=len(feedback_ids),
        status=card.status,
        classification=card.classification,
        confidence=float(card.confidence) if card.confidence is not None else None,
        rationale=card.rationale,
        draft_comment=card.draft_comment,
        proposed_action=card.proposed_action,
        proposed_labels=card.proposed_labels_json,
        suspected_files=suspected,
        duplicates=duplicates,
        reproduction_verdict=card.reproduction_verdict,
        reproduction_log=card.reproduction_log,
        budget_limited=bool(card.budget_limited),
        final_comment=card.final_comment,
        created_at=card.created_at,
    )
