from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, Repo, TriageCard, User
from bugsift.github.client import GithubClient

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
    issue_number: int
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


@router.get("", response_model=list[CardResponse])
async def list_cards(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 50,
    status: str | None = None,
    classification: str | None = None,
    verdict: str | None = None,
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
    stmt = stmt.order_by(TriageCard.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [_card_response(card, full_name, branch) for card, full_name, branch in rows]


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
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    github_client_factory = Depends(get_github_client_factory),
) -> CardResponse:
    card, repo, install = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    if not card.draft_comment:
        raise HTTPException(status_code=400, detail="card has no draft comment to post")

    client = github_client_factory(install.github_installation_id)

    try:
        await client.post_issue_comment(repo.full_name, card.issue_number, card.draft_comment)
    except Exception as e:
        logger.exception("failed to post comment card_id=%s", card_id)
        raise HTTPException(status_code=502, detail=f"failed to post comment: {e}") from e

    labels = card.proposed_labels_json or []
    if card.proposed_action == "comment_and_label" and labels:
        try:
            await client.add_labels(repo.full_name, card.issue_number, labels)
        except Exception:
            logger.warning("labels apply failed card_id=%s; continuing", card_id)

    if card.proposed_action == "comment_and_close":
        try:
            await client.close_issue(repo.full_name, card.issue_number)
        except Exception:
            logger.warning("close failed card_id=%s; continuing", card_id)

    card.status = "posted"
    card.final_comment = card.draft_comment
    card.decided_at = datetime.now(UTC)
    card.decided_by_user_id = user.id
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


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
    return CardResponse(
        id=card.id,
        repo_full_name=repo_full_name,
        repo_default_branch=repo_default_branch,
        issue_number=card.issue_number,
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
