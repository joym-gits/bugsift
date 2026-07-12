"""Monitoring/error-event ingest — generic-provider webhook.

Auth: per-repo opaque static token (``X-Bugsift-Monitor-Token`` header),
same shape as the feedback widget's ``X-Bugsift-App-Key``
(:mod:`bugsift.api.feedback`) — chosen over per-provider HMAC
verification because this endpoint is deliberately provider-agnostic
(Sentry/Datadog/custom outbound webhooks each sign differently; a
static bearer token is the lowest common denominator all of them
support). A specific provider's HMAC scheme can be layered on top
later as an additional check without changing this base shape.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, MonitoringEvent, MonitoringIngestToken, Repo, User
from bugsift.github.rate_limit import _client as _redis_client
from bugsift.monitoring.correlator import correlate_event
from bugsift.security.ip_utils import client_ip as _real_client_ip

router = APIRouter(prefix="/monitoring", tags=["monitoring"])
logger = logging.getLogger(__name__)

TOKEN_PREFIX = "mit_"
INGEST_RATE_LIMIT_PER_MIN = 60


async def _owned_repo(session: AsyncSession, user: User, repo_id: int) -> Repo:
    repo = (
        await session.execute(
            select(Repo)
            .join(Installation, Repo.installation_id == Installation.id)
            .where(Repo.id == repo_id, Installation.user_id == user.id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    return repo


async def _allow_monitoring_ingest(repo_id: int, client_ip: str) -> bool:
    """Same two-tier per-minute cap as the feedback widget's
    ``_allow_ingest`` — per-(repo, ip) and a looser per-repo ceiling."""
    client = _redis_client()
    per_ip_key = f"rate:monitor:{repo_id}:{client_ip}"
    per_repo_key = f"rate:monitor:repo:{repo_id}"
    per_ip = await client.incr(per_ip_key)
    if per_ip == 1:
        await client.expire(per_ip_key, 60)
    if per_ip > INGEST_RATE_LIMIT_PER_MIN:
        return False
    per_repo = await client.incr(per_repo_key)
    if per_repo == 1:
        await client.expire(per_repo_key, 60)
    return per_repo <= INGEST_RATE_LIMIT_PER_MIN * 10


# ---------- Ingest (external provider) ----------


class MonitoringEventIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    external_event_id: str = Field(min_length=1, max_length=255)
    level: str | None = Field(default=None, max_length=16)
    message: str = Field(min_length=1, max_length=8000)
    file_paths: list[str] = Field(default_factory=list, max_length=50)
    occurrence_count: int = Field(default=1, ge=1, le=1_000_000)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    raw_payload: dict | None = None


class MonitoringEventOut(BaseModel):
    id: int
    provider: str
    level: str | None
    message: str
    file_paths: list[str] | None
    occurrence_count: int
    correlated_card_id: int | None
    resolved_at: datetime | None
    resolution_status: str | None
    created_at: datetime


def _serialize_event(event: MonitoringEvent) -> MonitoringEventOut:
    return MonitoringEventOut(
        id=event.id,
        provider=event.provider,
        level=event.level,
        message=event.message,
        file_paths=event.file_paths_json,
        occurrence_count=event.occurrence_count,
        correlated_card_id=event.correlated_card_id,
        resolved_at=event.resolved_at,
        resolution_status=event.resolution_status,
        created_at=event.created_at,
    )


@router.post("/ingest", response_model=MonitoringEventOut, status_code=202)
async def ingest_monitoring_event(
    body: MonitoringEventIn,
    request: Request,
    x_bugsift_monitor_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> MonitoringEventOut:
    if not x_bugsift_monitor_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing X-Bugsift-Monitor-Token"
        )

    token_row = (
        await session.execute(
            select(MonitoringIngestToken).where(
                MonitoringIngestToken.token == x_bugsift_monitor_token,
                MonitoringIngestToken.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if token_row is None:
        # Same shape as "no token" so scrapers can't tell if a prefix is valid.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid monitor token"
        )

    ip = _real_client_ip(request)
    if not await _allow_monitoring_ingest(token_row.repo_id, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="ingest rate limit exceeded"
        )

    existing = (
        await session.execute(
            select(MonitoringEvent).where(
                MonitoringEvent.repo_id == token_row.repo_id,
                MonitoringEvent.provider == body.provider,
                MonitoringEvent.external_event_id == body.external_event_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.occurrence_count += body.occurrence_count
        existing.last_seen = body.last_seen or existing.last_seen
        event = existing
    else:
        event = MonitoringEvent(
            repo_id=token_row.repo_id,
            ingest_token_id=token_row.id,
            provider=body.provider,
            external_event_id=body.external_event_id,
            level=body.level,
            message=body.message.strip(),
            file_paths_json=body.file_paths or None,
            occurrence_count=body.occurrence_count,
            first_seen=body.first_seen,
            last_seen=body.last_seen,
            raw_payload_json=body.raw_payload,
            ingest_ip=ip,
        )
        session.add(event)
        await session.flush()
        matches = await correlate_event(
            session, repo_id=token_row.repo_id, file_paths=body.file_paths
        )
        if matches:
            event.correlated_card_id = matches[0].id

    await session.commit()
    await session.refresh(event)
    logger.info(
        "monitoring event ingested repo_id=%s provider=%s external_event_id=%s correlated_card_id=%s",
        token_row.repo_id,
        event.provider,
        event.external_event_id,
        event.correlated_card_id,
    )
    return _serialize_event(event)


# ---------- Dashboard CRUD (authenticated) ----------


class TokenOut(BaseModel):
    id: int
    repo_id: int
    token: str  # only ever returned here, at creation time
    created_at: datetime


@router.post("/repos/{repo_id}/tokens", response_model=TokenOut, status_code=201)
async def create_monitor_token(
    repo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TokenOut:
    await _owned_repo(session, user, repo_id)
    tok = MonitoringIngestToken(
        repo_id=repo_id,
        token=f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}",
        created_by_user_id=user.id,
    )
    session.add(tok)
    await session.commit()
    await session.refresh(tok)
    return TokenOut(id=tok.id, repo_id=tok.repo_id, token=tok.token, created_at=tok.created_at)


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_monitor_token(
    token_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    tok = (
        await session.execute(
            select(MonitoringIngestToken)
            .join(Repo, MonitoringIngestToken.repo_id == Repo.id)
            .join(Installation, Repo.installation_id == Installation.id)
            .where(MonitoringIngestToken.id == token_id, Installation.user_id == user.id)
        )
    ).scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=404, detail="token not found")
    tok.revoked_at = datetime.now(UTC)
    await session.commit()


@router.get("/events", response_model=list[MonitoringEventOut])
async def list_monitoring_events(
    repo_id: int,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MonitoringEventOut]:
    await _owned_repo(session, user, repo_id)
    rows = (
        (
            await session.execute(
                select(MonitoringEvent)
                .where(MonitoringEvent.repo_id == repo_id)
                .order_by(MonitoringEvent.created_at.desc())
                .limit(min(max(limit, 1), 200))
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_event(e) for e in rows]
