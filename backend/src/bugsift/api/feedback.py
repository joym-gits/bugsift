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
    FeedbackDigest,
    FeedbackReport,
    Installation,
    Repo,
    RepoAnalysis,
    RepoAnalysisChatMessage,
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


# ---------- Q&A over the analysis ----------


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[dict] | None = None
    created_at: datetime


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


async def _owned_analysis(
    session: AsyncSession, user: User, app_id: int
) -> tuple[RepoAnalysis, Repo]:
    """Fetch the RepoAnalysis behind a feedback app, enforcing ownership
    and returning the repo so callers can report its full_name."""
    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="app not found")
    if app.default_repo_id is None:
        raise HTTPException(
            status_code=400, detail="app has no default repo"
        )
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
    if analysis is None or analysis.status != "ready":
        raise HTTPException(
            status_code=400,
            detail="run an analysis first — Q&A needs the ready analysis",
        )
    return analysis, repo


@router.get(
    "/feedback/apps/{app_id}/chats", response_model=list[ChatMessageOut]
)
async def list_analysis_chats(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ChatMessageOut]:
    analysis, _ = await _owned_analysis(session, user, app_id)
    rows = (
        await session.execute(
            select(RepoAnalysisChatMessage)
            .where(RepoAnalysisChatMessage.analysis_id == analysis.id)
            .order_by(RepoAnalysisChatMessage.created_at.asc())
        )
    ).scalars().all()
    return [
        ChatMessageOut(
            id=r.id,
            role=r.role,
            content=r.content,
            citations=r.citations_json if isinstance(r.citations_json, list) else None,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/feedback/apps/{app_id}/chats", response_model=list[ChatMessageOut]
)
async def ask_analysis_chat(
    app_id: int,
    body: AskBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ChatMessageOut]:
    """Ask a question about the repo. Persists the user turn, retrieves
    context, calls the LLM, persists the assistant turn, and returns
    both new rows so the dashboard can append them without re-fetching
    the whole history."""
    from decimal import Decimal

    from bugsift.analysis.qa import answer_question
    from bugsift.db.models import Installation
    from bugsift.llm.factory import get_provider_for_user
    from bugsift.retrieval.embedding import (
        EmbeddingUnavailable,
        get_embedder_for_repo,
    )
    from bugsift.security import crypto
    from bugsift.workers.triage import DEFAULT_PROVIDER

    analysis, repo = await _owned_analysis(session, user, app_id)

    # Load the user's completion provider — same selection logic as
    # triage (anthropic by default).
    install = await session.get(Installation, repo.installation_id)
    if install is None or install.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="repo has no installation linked; cannot answer",
        )
    try:
        owner = await session.get(User, install.user_id)
        provider = await get_provider_for_user(
            session, owner, DEFAULT_PROVIDER
        )
    except (KeyError, crypto.DecryptionFailed) as e:
        raise HTTPException(
            status_code=400,
            detail=f"no usable {DEFAULT_PROVIDER} key for the owner: {e}",
        ) from e

    # Embedder — reuse the one the analysis was built with.
    try:
        embed_provider, choice = await get_embedder_for_repo(
            session, repo, install.user_id
        )
    except EmbeddingUnavailable as e:
        raise HTTPException(
            status_code=400,
            detail=f"embedder not available: {e}",
        ) from e

    # Load history to feed the LLM. Cheap; analysis chats are small.
    history_rows = (
        await session.execute(
            select(RepoAnalysisChatMessage)
            .where(RepoAnalysisChatMessage.analysis_id == analysis.id)
            .order_by(RepoAnalysisChatMessage.created_at.asc())
        )
    ).scalars().all()
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    # Persist the user turn first so a crash downstream still leaves a
    # breadcrumb.
    user_msg = RepoAnalysisChatMessage(
        analysis_id=analysis.id,
        role="user",
        content=body.question.strip(),
    )
    session.add(user_msg)
    await session.commit()
    await session.refresh(user_msg)

    try:
        result = await answer_question(
            session,
            analysis=analysis,
            question=body.question,
            history=history,
            provider=provider,
            embed_provider=embed_provider,
            embedding_dim=choice.dim,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("qa: LLM call failed for analysis_id=%s", analysis.id)
        raise HTTPException(status_code=502, detail=f"Q&A failed: {e}") from e

    assistant_msg = RepoAnalysisChatMessage(
        analysis_id=analysis.id,
        role="assistant",
        content=result.answer,
        citations_json=[c.__dict__ for c in result.citations] or None,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=(
            Decimal(f"{result.cost_usd:.6f}") if result.cost_usd else None
        ),
    )
    session.add(assistant_msg)
    await session.commit()
    await session.refresh(assistant_msg)

    return [
        ChatMessageOut(
            id=user_msg.id,
            role="user",
            content=user_msg.content,
            citations=None,
            created_at=user_msg.created_at,
        ),
        ChatMessageOut(
            id=assistant_msg.id,
            role="assistant",
            content=assistant_msg.content,
            citations=assistant_msg.citations_json
            if isinstance(assistant_msg.citations_json, list)
            else None,
            created_at=assistant_msg.created_at,
        ),
    ]


# ---------- Weekly trends / digest ----------


class DigestClusterOut(BaseModel):
    size: int
    representative: str
    report_ids: list[int]
    card_ids: list[int]


class DigestTopFileOut(BaseModel):
    file_path: str
    card_count: int


class DigestOut(BaseModel):
    id: int | None = None
    app_id: int
    period_start: datetime
    period_end: datetime
    report_count: int
    previous_report_count: int
    clusters: list[DigestClusterOut]
    top_files: list[DigestTopFileOut]
    severity_breakdown: dict[str, int]
    generated_at: datetime


@router.post(
    "/feedback/apps/{app_id}/digests/current", response_model=DigestOut
)
async def compute_current_digest(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DigestOut:
    """Compute (or refresh) the digest for the current weekly window.

    Upserts on ``(app_id, period_start)`` so calling this repeatedly
    keeps one row per week; the last call wins. Runs inline — the
    cluster pass is cheap (tens/hundreds of reports, Python cosine).
    """
    from bugsift.feedback.digest import compute_digest, current_weekly_window

    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="app not found")

    period_start, period_end = current_weekly_window()
    result = await compute_digest(
        session, app=app, period_start=period_start, period_end=period_end
    )

    row = (
        await session.execute(
            select(FeedbackDigest).where(
                FeedbackDigest.app_id == app.id,
                FeedbackDigest.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = FeedbackDigest(
            app_id=app.id,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(row)
    row.period_end = period_end
    row.report_count = result.report_count
    row.previous_report_count = result.previous_report_count
    row.clusters_json = result.clusters
    row.top_files_json = result.top_files
    row.severity_breakdown_json = result.severity_breakdown
    # Generated-at auto-updates via server_default on INSERT; bump it
    # explicitly on UPDATE so the UI reflects the recompute time.
    from datetime import UTC as _UTC, datetime as _dt

    row.generated_at = _dt.now(_UTC)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "digest: app_id=%s period_start=%s reports=%d clusters=%d",
        app_id,
        period_start.isoformat(),
        result.report_count,
        len(result.clusters),
    )
    return _serialize_digest(row)


@router.get("/feedback/apps/{app_id}/digests", response_model=list[DigestOut])
async def list_digests(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 12,
) -> list[DigestOut]:
    """Most recent N digests (default last 12 weeks)."""
    app = await session.get(FeedbackApp, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="app not found")
    rows = (
        await session.execute(
            select(FeedbackDigest)
            .where(FeedbackDigest.app_id == app.id)
            .order_by(FeedbackDigest.period_start.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_serialize_digest(r) for r in rows]


def _serialize_digest(row: FeedbackDigest) -> DigestOut:
    clusters = row.clusters_json if isinstance(row.clusters_json, list) else []
    top_files = row.top_files_json if isinstance(row.top_files_json, list) else []
    severity = (
        row.severity_breakdown_json
        if isinstance(row.severity_breakdown_json, dict)
        else {}
    )
    return DigestOut(
        id=row.id,
        app_id=row.app_id,
        period_start=row.period_start,
        period_end=row.period_end,
        report_count=row.report_count,
        previous_report_count=row.previous_report_count,
        clusters=[
            DigestClusterOut(
                size=int(c.get("size", 0)),
                representative=str(c.get("representative", "")),
                report_ids=[int(x) for x in (c.get("report_ids") or []) if isinstance(x, int)],
                card_ids=[int(x) for x in (c.get("card_ids") or []) if isinstance(x, int)],
            )
            for c in clusters
            if isinstance(c, dict)
        ],
        top_files=[
            DigestTopFileOut(
                file_path=str(f.get("file_path", "")),
                card_count=int(f.get("card_count", 0)),
            )
            for f in top_files
            if isinstance(f, dict)
        ],
        severity_breakdown={str(k): int(v) for k, v in severity.items() if isinstance(v, int)},
        generated_at=row.generated_at,
    )


@router.delete("/feedback/apps/{app_id}/chats", status_code=204)
async def clear_analysis_chats(
    app_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    analysis, _ = await _owned_analysis(session, user, app_id)
    await session.execute(
        RepoAnalysisChatMessage.__table__.delete().where(
            RepoAnalysisChatMessage.analysis_id == analysis.id
        )
    )
    await session.commit()


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
