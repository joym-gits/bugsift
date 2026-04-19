"""Feedback ingestion API.

Two surfaces:

- ``POST /ingest/feedback`` — public endpoint the widget calls. Auth is the
  ``X-Bugsift-App-Key`` header (the ``public_key`` column). Browser origins
  can be narrowed per-app; otherwise we rate-limit per IP and accept the
  request. Responds with ``{ report_id }``.

- ``/feedback/apps`` CRUD — authenticated dashboard surface so the operator
  can create an app (get a public key + embed snippet) and list / revoke
  them. Only the owning user sees their apps.

No triage happens here yet (slice 2 wires the orchestrator). Raw reports
land in ``feedback_reports`` and stay there until the pipeline picks them
up.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    Repo,
    RepoAnalysis,
    User,
)
from bugsift.github.rate_limit import _client as _redis_client
from bugsift.workers import enqueue as enqueue_jobs

# Thin alias so tests can monkey-patch a single symbol without reaching
# into the workers module.
_enqueue_feedback_triage = enqueue_jobs.enqueue_feedback_triage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])

PUBLIC_KEY_PREFIX = "pk_"
MAX_BODY_BYTES = 32 * 1024  # 32 KB is generous for free-form feedback
MAX_CONSOLE_BYTES = 32 * 1024
INGEST_RATE_LIMIT_PER_MIN = 60


# ---------- Ingest (widget) ----------


class IngestBody(BaseModel):
    """Payload the widget POSTs. Everything except ``text`` is optional so
    minimal integrations (e.g. a CLI calling us directly) work, and so the
    widget can degrade gracefully when the host app blocks certain APIs."""

    text: str = Field(min_length=1, max_length=MAX_BODY_BYTES)
    url: str | None = Field(default=None, max_length=2048)
    user_agent: str | None = Field(default=None, max_length=512)
    app_version: str | None = Field(default=None, max_length=120)
    console_log: str | None = Field(default=None, max_length=MAX_CONSOLE_BYTES)
    screenshot_url: str | None = Field(default=None, max_length=2048)
    reporter_id: str | None = Field(default=None, max_length=320)
    client_meta: dict | None = None


class IngestResponse(BaseModel):
    report_id: int


@router.post("/ingest/feedback", response_model=IngestResponse, status_code=202)
async def ingest_feedback(
    body: IngestBody,
    request: Request,
    x_bugsift_app_key: str | None = Header(default=None),
    origin: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> IngestResponse:
    if not x_bugsift_app_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Bugsift-App-Key",
        )

    app = (
        await session.execute(
            select(FeedbackApp).where(FeedbackApp.public_key == x_bugsift_app_key)
        )
    ).scalar_one_or_none()
    if app is None:
        # Same shape as "no key" so scrapers can't tell if a prefix is valid.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid app key"
        )

    if app.allowed_origins_json:
        # Exact-match allowlist. Mobile / server callers send no Origin,
        # which we treat as blocked when the app opted into the allowlist.
        if origin is None or origin not in app.allowed_origins_json:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="origin not allowed for this app",
            )

    client_ip = (request.client.host if request.client else None) or "unknown"
    if not await _allow_ingest(app.id, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="ingest rate limit exceeded",
        )

    report = FeedbackReport(
        app_id=app.id,
        body_text=body.text.strip(),
        url=(body.url or None),
        user_agent=(body.user_agent or None),
        app_version=(body.app_version or None),
        console_log=(body.console_log or None),
        screenshot_url=(body.screenshot_url or None),
        reporter_hash=_hash_reporter(body.reporter_id),
        client_meta_json=body.client_meta,
        content_hash=_content_hash(body.text),
        ingest_ip=client_ip,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    logger.info(
        "feedback ingested app_id=%s report_id=%s len=%d",
        app.id,
        report.id,
        len(body.text),
    )
    # Kick triage asynchronously — the widget gets a 202 regardless of
    # how long the pipeline takes. If redis is unreachable we still want
    # the raw report persisted, so swallow enqueue errors into the log.
    try:
        _enqueue_feedback_triage(report.id)
    except Exception:
        logger.exception(
            "feedback triage enqueue failed for report_id=%s; report is persisted "
            "and can be re-triaged later",
            report.id,
        )
    return IngestResponse(report_id=report.id)


# ---------- Dashboard CRUD ----------


class CreateAppBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    default_repo_id: int | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=20)
    target_branch: str | None = Field(default=None, max_length=255)


class UpdateAppBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_repo_id: int | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=20)
    target_branch: str | None = Field(default=None, max_length=255)


class FeedbackAppOut(BaseModel):
    id: int
    name: str
    public_key: str
    default_repo_id: int | None
    default_repo_full_name: str | None
    default_repo_branch: str | None
    target_branch: str | None
    allowed_origins: list[str] | None
    created_at: datetime
    report_count: int


@router.post("/feedback/apps", response_model=FeedbackAppOut, status_code=201)
async def create_feedback_app(
    body: CreateAppBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FeedbackAppOut:
    if body.default_repo_id is not None:
        owned = await _owns_repo(session, user.id, body.default_repo_id)
        if not owned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="default_repo_id is not a repo you own",
            )

    cleaned_origins = _clean_origins(body.allowed_origins) if body.allowed_origins else None
    row = FeedbackApp(
        user_id=user.id,
        name=body.name.strip(),
        public_key=_generate_public_key(),
        allowed_origins_json=cleaned_origins,
        default_repo_id=body.default_repo_id,
        target_branch=(body.target_branch or "").strip() or None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("feedback app created id=%s user_id=%s", row.id, user.id)
    return await _serialize(session, row)


@router.patch("/feedback/apps/{app_id}", response_model=FeedbackAppOut)
async def update_feedback_app(
    app_id: int,
    body: UpdateAppBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FeedbackAppOut:
    row = await session.get(FeedbackApp, app_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="app not found")

    if body.name is not None:
        row.name = body.name.strip()
    if body.default_repo_id is not None:
        if not await _owns_repo(session, user.id, body.default_repo_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="default_repo_id is not a repo you own",
            )
        row.default_repo_id = body.default_repo_id
    if body.allowed_origins is not None:
        row.allowed_origins_json = _clean_origins(body.allowed_origins) or None
    if body.target_branch is not None:
        branch = body.target_branch.strip()
        row.target_branch = branch or None
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.get("/feedback/apps", response_model=list[FeedbackAppOut])
async def list_feedback_apps(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[FeedbackAppOut]:
    rows = (
        await session.execute(
            select(FeedbackApp)
            .where(FeedbackApp.user_id == user.id)
            .order_by(FeedbackApp.created_at.desc())
        )
    ).scalars().all()
    return [await _serialize(session, r) for r in rows]


class AnalysisResponse(BaseModel):
    id: int
    repo_id: int
    branch: str
    status: str
    structured_json: dict | None
    mermaid_src: str | None
    overrides: list[str]
    error_detail: str | None
    generated_at: datetime | None
    updated_at: datetime


class CorrectionBody(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.post(
    "/feedback/apps/{app_id}/analyze",
    response_model=AnalysisResponse,
    status_code=202,
)
async def kick_feedback_app_analysis(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """Enqueue a full repo analysis for the repo behind this feedback app.

    Idempotent: enqueuing while a previous analysis is still ``running``
    returns the existing row so the dashboard can keep polling. The
    worker overwrites the row when it finishes.
    """
    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="app not found")
    if app.default_repo_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="set a default repo on the app before analysing",
        )
    repo = await session.get(Repo, app.default_repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repo not found")

    branch = (app.target_branch or repo.default_branch or "main").strip()
    analysis = (
        await session.execute(
            select(RepoAnalysis).where(
                RepoAnalysis.repo_id == repo.id, RepoAnalysis.branch == branch
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        analysis = RepoAnalysis(repo_id=repo.id, branch=branch, status="pending")
        session.add(analysis)
    else:
        analysis.status = "pending"
        analysis.error_detail = None
    await session.commit()
    await session.refresh(analysis)

    enqueue_jobs.enqueue_analyze_feedback_app(app.id)
    logger.info(
        "analysis queued app_id=%s repo_id=%s branch=%s", app.id, repo.id, branch
    )
    return _serialize_analysis(analysis)


@router.get("/feedback/apps/{app_id}/analysis", response_model=AnalysisResponse | None)
async def get_feedback_app_analysis(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnalysisResponse | None:
    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="app not found")
    if app.default_repo_id is None:
        return None
    repo = await session.get(Repo, app.default_repo_id)
    if repo is None:
        return None
    branch = (app.target_branch or repo.default_branch or "main").strip()
    analysis = (
        await session.execute(
            select(RepoAnalysis).where(
                RepoAnalysis.repo_id == repo.id, RepoAnalysis.branch == branch
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        return None
    return _serialize_analysis(analysis)


@router.post(
    "/feedback/apps/{app_id}/analysis/corrections",
    response_model=AnalysisResponse,
)
async def add_analysis_correction(
    app_id: int,
    body: CorrectionBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnalysisResponse:
    """Append a human override to the current analysis.

    Corrections are a list of free-form strings; the worker injects
    them into the top-level synthesis prompt on the next regeneration
    so the LLM has to respect them. This endpoint only records the
    override — the caller should follow with a POST to ``/analyze`` to
    actually regenerate.
    """
    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="app not found")
    if app.default_repo_id is None:
        raise HTTPException(status_code=400, detail="app has no default repo")
    repo = await session.get(Repo, app.default_repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    branch = (app.target_branch or repo.default_branch or "main").strip()
    analysis = (
        await session.execute(
            select(RepoAnalysis).where(
                RepoAnalysis.repo_id == repo.id, RepoAnalysis.branch == branch
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(
            status_code=400,
            detail="run an analysis first — no current result to correct",
        )
    overrides = list(analysis.overrides_json or [])
    overrides.append(body.note.strip())
    analysis.overrides_json = overrides
    await session.commit()
    await session.refresh(analysis)
    return _serialize_analysis(analysis)


def _serialize_analysis(analysis: RepoAnalysis) -> AnalysisResponse:
    return AnalysisResponse(
        id=analysis.id,
        repo_id=analysis.repo_id,
        branch=analysis.branch,
        status=analysis.status,
        structured_json=analysis.structured_json,
        mermaid_src=analysis.mermaid_src,
        overrides=list(analysis.overrides_json or []),
        error_detail=analysis.error_detail,
        generated_at=analysis.generated_at,
        updated_at=analysis.updated_at,
    )


@router.delete("/feedback/apps/{app_id}", status_code=204)
async def delete_feedback_app(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    row = await session.get(FeedbackApp, app_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="app not found")
    await session.delete(row)
    await session.commit()
    logger.info("feedback app deleted id=%s user_id=%s", app_id, user.id)


# ---------- helpers ----------


_PUBLIC_KEY_ALPHABET = re.compile(r"^[a-zA-Z0-9_-]+$")


def _generate_public_key() -> str:
    """URL-safe 40-char random string, prefixed so operators can recognise
    it in logs at a glance. No secret paired with it yet — widget-only v1."""
    return PUBLIC_KEY_PREFIX + secrets.token_urlsafe(30)[:40]


def _content_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_reporter(reporter_id: str | None) -> str | None:
    if not reporter_id:
        return None
    return hashlib.sha256(reporter_id.strip().encode("utf-8")).hexdigest()


def _clean_origins(origins: list[str]) -> list[str]:
    out: list[str] = []
    for o in origins:
        o = o.strip().rstrip("/")
        if not o:
            continue
        # Cap at a sane length; reject obvious garbage.
        if len(o) > 253 or any(c.isspace() for c in o):
            continue
        out.append(o)
    return out


async def _owns_repo(session: AsyncSession, user_id: int, repo_id: int) -> bool:
    row = (
        await session.execute(
            select(Repo.id)
            .join(Installation, Repo.installation_id == Installation.id)
            .where(Repo.id == repo_id, Installation.user_id == user_id)
        )
    ).first()
    return row is not None


async def _serialize(session: AsyncSession, app: FeedbackApp) -> FeedbackAppOut:
    repo_full_name: str | None = None
    repo_branch: str | None = None
    if app.default_repo_id is not None:
        repo = await session.get(Repo, app.default_repo_id)
        if repo is not None:
            repo_full_name = repo.full_name
            repo_branch = repo.default_branch
    # Tiny count query; fine at this scale. If feedback_reports grows huge,
    # materialise a counter column on feedback_apps.
    from sqlalchemy import func as _f

    count = (
        await session.execute(
            select(_f.count(FeedbackReport.id)).where(FeedbackReport.app_id == app.id)
        )
    ).scalar_one()
    return FeedbackAppOut(
        id=app.id,
        name=app.name,
        public_key=app.public_key,
        default_repo_id=app.default_repo_id,
        default_repo_full_name=repo_full_name,
        default_repo_branch=repo_branch,
        target_branch=app.target_branch,
        allowed_origins=app.allowed_origins_json,
        created_at=app.created_at,
        report_count=int(count),
    )


async def _allow_ingest(app_id: int, client_ip: str) -> bool:
    """Per-minute cap keyed on ``(app_id, client_ip)``. Bumps the counter;
    first hit of a window gets a 60s TTL. Outside the limit returns False."""
    client = _redis_client()
    key = f"rate:ingest:{app_id}:{client_ip}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60)
    return count <= INGEST_RATE_LIMIT_PER_MIN
