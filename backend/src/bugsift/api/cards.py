from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bugsift.api.deps import get_current_user, get_session
from bugsift.audit.log import Action, record as audit_record
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    TicketDestination,
    TriageCard,
    User,
)
from bugsift.feedback import issue_body as feedback_issue_body
from bugsift.github import config as app_config
from bugsift.github.client import GithubClient
from bugsift.security import crypto
from bugsift.tickets.jira import JiraApiError, JiraAuthError, JiraClient
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


class RegressionSuspectOut(BaseModel):
    commit_sha: str
    short_sha: str
    message_first_line: str
    author_name: str | None = None
    author_login: str | None = None
    pushed_at_iso: str
    pr_number: int | None = None
    ref: str | None = None
    overlapping_paths: list[str]


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
    ticket_provider: str | None = None
    ticket_key: str | None = None
    ticket_url: str | None = None
    feedback_report_count: int = 0
    status: str
    classification: str | None
    severity: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    draft_comment: str | None = None
    proposed_action: str | None = None
    proposed_labels: list[str] | None = None
    suspected_files: list[SuspectedFileOut] | None = None
    suggested_assignees: list[str] | None = None
    duplicates: list[DuplicateOut] | None = None
    regression_suspects: list[RegressionSuspectOut] | None = None
    reproduction_verdict: str | None = None
    reproduction_log: str | None = None
    budget_limited: bool = False
    # Kinds + counts of PII the redactor scrubbed before the prompt
    # went to the LLM. ``null`` = card predates the redactor; ``{}`` =
    # clean; populated dict = show a pill on the tile.
    pii_redacted: dict[str, int] | None = None
    # SLA set by a matching routing rule. Minutes from ``created_at``
    # after which a still-pending card is considered breached.
    sla_minutes: int | None = None
    sla_breach_alerted_at: datetime | None = None
    final_comment: str | None = None
    created_at: datetime


class EditBody(BaseModel):
    draft_comment: str


class ApproveBody(BaseModel):
    """Optional body on approve.

    - ``admin_note`` (feedback cards only) is rendered into the new
      tracker issue's body.
    - ``assignees`` overrides the card's ``suggested_assignees_json``.
      ``None`` means "use the card's suggestions as-is"; an empty list
      means "don't assign anybody". This lets the dashboard checkbox
      UI explicitly narrow or clear the assignee set before approving.
    """

    admin_note: str | None = Field(default=None, max_length=8000)
    assignees: list[str] | None = Field(default=None, max_length=10)


@router.get("", response_model=list[CardResponse])
async def list_cards(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 50,
    status: str | None = None,
    classification: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    severity: str | None = None,
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
    if severity:
        stmt = stmt.where(TriageCard.severity == severity)
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
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> CardResponse:
    card, repo, _ = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    card.draft_comment = body.draft_comment
    await audit_record(
        session,
        actor=user,
        action=Action.CARD_EDITED,
        target_type="card",
        target_id=card.id,
        summary=f"edited draft on {repo.full_name}#{card.issue_number or ''}".rstrip("#"),
        request=request,
    )
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


@router.post("/{card_id}/rerun", status_code=202)
async def rerun_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
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
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> CardResponse:
    card, repo, _ = await _get_owned_card(session, user, card_id)
    if card.status != "pending":
        raise HTTPException(status_code=409, detail=f"card is already {card.status}")
    card.status = "skipped"
    card.decided_at = datetime.now(UTC)
    card.decided_by_user_id = user.id
    await audit_record(
        session,
        actor=user,
        action=Action.CARD_SKIPPED,
        target_type="card",
        target_id=card.id,
        summary=f"skipped {repo.full_name}#{card.issue_number or ''}".rstrip("#"),
        metadata={"classification": card.classification, "severity": card.severity},
        request=request,
    )
    await session.commit()
    await session.refresh(card)
    return _card_response(card, repo.full_name, repo.default_branch)


@router.post("/{card_id}/approve", response_model=CardResponse)
async def approve_card(
    card_id: int,
    request: Request,
    body: ApproveBody | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
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

    assignees_override = body.assignees if body is not None else None
    if card.source == "feedback":
        await _approve_feedback_card(
            session=session,
            card=card,
            repo=repo,
            user=user,
            client=client,
            admin_note=(body.admin_note if body else None),
            assignees_override=assignees_override,
        )
    else:
        await _approve_github_card(
            card=card, repo=repo, client=client, assignees_override=assignees_override
        )
        card.final_comment = card.draft_comment
        # Populate generic ticket_* columns for existing github cards
        # so the UI can link out uniformly regardless of destination.
        if card.issue_number is not None:
            card.ticket_provider = "github"
            card.ticket_key = str(card.issue_number)
            card.ticket_url = (
                f"https://github.com/{repo.full_name}/issues/{card.issue_number}"
            )

    card.status = "posted"
    card.decided_at = datetime.now(UTC)
    card.decided_by_user_id = user.id
    await audit_record(
        session,
        actor=user,
        action=Action.CARD_APPROVED,
        target_type="card",
        target_id=card.id,
        summary=f"approved {repo.full_name}#{card.issue_number or ''}".rstrip("#"),
        metadata={
            "classification": card.classification,
            "severity": card.severity,
            "assignees": list(assignees_override or []),
            "ticket_provider": card.ticket_provider,
            "ticket_key": card.ticket_key,
        },
        request=request,
    )
    await session.commit()
    await session.refresh(card)
    try:
        enqueue_jobs.enqueue_slack_notification(card.id, "approved")
    except Exception:
        logger.exception(
            "slack: enqueue failed for card_id=%s after approve; continuing",
            card.id,
        )
    return _card_response(card, repo.full_name, repo.default_branch)


async def _approve_github_card(
    *,
    card: TriageCard,
    repo: Repo,
    client,
    assignees_override: list[str] | None = None,
) -> None:
    """Classic flow: comment on the existing GitHub issue, optionally
    apply labels, optionally close. Also applies any CODEOWNERS-
    suggested assignees the triage pipeline picked — best-effort, so
    GitHub silently dropping non-member logins doesn't block the
    comment."""
    if not card.draft_comment:
        raise HTTPException(status_code=400, detail="card has no draft comment to post")
    try:
        await client.post_issue_comment(repo.full_name, card.issue_number, card.draft_comment)
    except Exception as e:
        logger.exception("failed to post comment card_id=%s", card.id)
        raise HTTPException(status_code=502, detail=f"failed to post comment: {e}") from e

    assignees = _resolve_assignees(card, assignees_override)
    if assignees:
        try:
            await client.add_assignees(
                repo.full_name, card.issue_number, assignees
            )
        except Exception:
            logger.warning(
                "assignees apply failed card_id=%s; continuing", card.id
            )

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
    assignees_override: list[str] | None = None,
) -> None:
    """Open a tracker issue for a widget-sourced feedback card.

    Routes to the feedback app's configured ticket destination:
    - ``None`` / destination missing → GitHub (existing behaviour), using
      the app's default repo.
    - Jira destination → create a Jira issue via the stored site URL +
      token and stamp the card with ``PROJ-NNN``.
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

    destination = await _resolve_ticket_destination(session, report_rows)
    if destination and destination.provider == "jira":
        await _create_jira_issue_for_card(
            card=card,
            destination=destination,
            title=title,
            body=body,
            labels=labels,
            repo_full_name=repo.full_name,
        )
        return

    # Default: GitHub Issues in the app's default repo (existing flow).
    assignees = _resolve_assignees(card, assignees_override)
    try:
        created = await client.create_issue(
            repo.full_name,
            title=title,
            body=body,
            labels=labels or None,
            assignees=assignees or None,
        )
    except Exception as e:
        logger.exception("failed to create GitHub issue card_id=%s", card.id)
        raise HTTPException(
            status_code=502, detail=f"failed to create GitHub issue: {e}"
        ) from e

    github_number = created.get("number")
    if isinstance(github_number, int):
        card.github_issue_number = github_number
        card.ticket_provider = "github"
        card.ticket_key = str(github_number)
        card.ticket_url = f"https://github.com/{repo.full_name}/issues/{github_number}"
    card.final_comment = body
    logger.info(
        "feedback card_id=%s opened github issue %s#%s",
        card.id,
        repo.full_name,
        github_number,
    )


async def _resolve_ticket_destination(
    session: AsyncSession, report_rows: list[FeedbackReport]
) -> TicketDestination | None:
    """Find the ticket destination pinned to the feedback app the first
    report belongs to. A card should always have at least one report
    (caller already guarded); we read the app from that anchor."""
    if not report_rows:
        return None
    app = await session.get(FeedbackApp, report_rows[0].app_id)
    if app is None or app.ticket_destination_id is None:
        return None
    return await session.get(TicketDestination, app.ticket_destination_id)


async def _create_jira_issue_for_card(
    *,
    card: TriageCard,
    destination: TicketDestination,
    title: str,
    body: str,
    labels: list[str],
    repo_full_name: str,
) -> None:
    """Call the customer's Jira instance to open an issue, then stamp
    the card with the resulting ``PROJ-NNN`` key + browse URL."""
    try:
        token = crypto.decrypt(destination.auth_token_encrypted)
    except crypto.DecryptionFailed as e:
        raise HTTPException(
            status_code=500,
            detail="could not decrypt the stored Jira token",
        ) from e

    config = destination.config_json or {}
    site_url = str(config.get("site_url") or "")
    user_email = str(config.get("user_email") or "")
    project_key = str(config.get("default_project_key") or "")
    issue_type = str(config.get("default_issue_type") or "Bug")
    if not site_url or not user_email or not project_key:
        raise HTTPException(
            status_code=400,
            detail="Jira destination is missing site URL, email, or project key",
        )

    jira = JiraClient(
        site_url=site_url, user_email=user_email, api_token=token
    )
    try:
        created = await jira.create_issue(
            project_key=project_key,
            issue_type=issue_type,
            summary=title,
            description=body,
            labels=labels or None,
        )
    except JiraAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except JiraApiError:
        logger.exception("failed to create Jira issue card_id=%s", card.id)
        raise HTTPException(
            status_code=502,
            detail="Failed to create Jira issue. Server logs have the full error.",
        )

    card.ticket_provider = "jira"
    card.ticket_key = created.key
    card.ticket_url = created.url
    card.final_comment = body
    logger.info(
        "feedback card_id=%s opened jira issue %s (repo=%s)",
        card.id,
        created.key,
        repo_full_name,
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


def _assignees_from_card(card: TriageCard) -> list[str]:
    raw = card.suggested_assignees_json
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]


def _resolve_assignees(
    card: TriageCard, override: list[str] | None
) -> list[str]:
    """Pick the assignee list to apply on approve.

    ``override is None`` → use the card's suggestions as-is. ``override == []``
    → explicitly assign nobody (operator unchecked all of them). Any
    non-empty list is filtered against the card's suggested list so a
    request can't smuggle arbitrary GitHub logins through."""
    if override is None:
        return _assignees_from_card(card)
    suggested = set(_assignees_from_card(card))
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in override:
        if not isinstance(raw, str):
            continue
        login = raw.strip().lstrip("@")
        if not login or login in seen:
            continue
        if login not in suggested:
            # Silently drop logins the CODEOWNERS matcher didn't produce —
            # we don't want this endpoint to become a general "assign this
            # user" knob that bypasses the server-side check.
            continue
        seen.add(login)
        cleaned.append(login)
    return cleaned


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
    regression_suspects = None
    if card.regression_suspects_json and isinstance(card.regression_suspects_json, list):
        regression_suspects = []
        for item in card.regression_suspects_json:
            if not isinstance(item, dict):
                continue
            overlap = item.get("overlapping_paths") or []
            regression_suspects.append(
                RegressionSuspectOut(
                    commit_sha=str(item.get("commit_sha", "")),
                    short_sha=str(item.get("short_sha", "")),
                    message_first_line=str(item.get("message_first_line", "")),
                    author_name=item.get("author_name"),
                    author_login=item.get("author_login"),
                    pushed_at_iso=str(item.get("pushed_at_iso", "")),
                    pr_number=item.get("pr_number"),
                    ref=item.get("ref"),
                    overlapping_paths=[str(p) for p in overlap if isinstance(p, str)],
                )
            )
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
        ticket_provider=card.ticket_provider,
        ticket_key=card.ticket_key,
        ticket_url=card.ticket_url,
        feedback_report_count=len(feedback_ids),
        status=card.status,
        classification=card.classification,
        severity=card.severity,
        confidence=float(card.confidence) if card.confidence is not None else None,
        rationale=card.rationale,
        draft_comment=card.draft_comment,
        proposed_action=card.proposed_action,
        proposed_labels=card.proposed_labels_json,
        suspected_files=suspected,
        suggested_assignees=(_assignees_from_card(card) or None),
        duplicates=duplicates,
        regression_suspects=regression_suspects,
        reproduction_verdict=card.reproduction_verdict,
        reproduction_log=card.reproduction_log,
        budget_limited=bool(card.budget_limited),
        pii_redacted=(
            dict(card.pii_redacted_json)
            if isinstance(card.pii_redacted_json, dict)
            else None
        ),
        sla_minutes=card.sla_minutes,
        sla_breach_alerted_at=card.sla_breach_alerted_at,
        final_comment=card.final_comment,
        created_at=card.created_at,
    )
