"""CRUD for Slack Incoming Webhook destinations + a test endpoint.

Incoming webhooks are channel-scoped URLs the user creates on Slack's
side (``https://api.slack.com/apps`` → create app → Incoming Webhooks →
Add New Webhook to Workspace). No OAuth app registration needed on our
side for v1; full Slack App + interactive buttons is a v2 feature that
needs a public bugsift URL + signing secret.

URLs are Fernet-encrypted at rest alongside the LLM + Sentry token
paths. We refuse to save anything that doesn't look like a Slack
webhook to catch typos early.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import SlackDestination, User
from bugsift.security import crypto
from bugsift.slack import notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack"])

_WEBHOOK_URL_RE = re.compile(
    r"^https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+$"
)


class CreateDestinationBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    webhook_url: str = Field(min_length=1, max_length=255)
    channel_hint: str | None = Field(default=None, max_length=120)
    # Map of event name -> bool. Unknown keys are silently dropped so a
    # future event name added in the UI doesn't break older clients.
    events: dict[str, bool] | None = None


class UpdateDestinationBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    channel_hint: str | None = Field(default=None, max_length=120)
    events: dict[str, bool] | None = None


class DestinationOut(BaseModel):
    id: int
    name: str
    channel_hint: str | None
    webhook_hint: str
    events: dict[str, bool]
    created_at: datetime


@router.get("/destinations", response_model=list[DestinationOut])
async def list_destinations(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[DestinationOut]:
    rows = (
        await session.execute(
            select(SlackDestination)
            .where(SlackDestination.user_id == user.id)
            .order_by(SlackDestination.created_at.desc())
        )
    ).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("/destinations", response_model=DestinationOut, status_code=201)
async def create_destination(
    body: CreateDestinationBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> DestinationOut:
    url = body.webhook_url.strip()
    if not _WEBHOOK_URL_RE.match(url):
        raise HTTPException(
            status_code=400,
            detail="not a valid Slack webhook URL — expected https://hooks.slack.com/services/…",
        )
    try:
        encrypted = crypto.encrypt(url)
    except crypto.EncryptionKeyMissing as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    events = _clean_events(body.events)
    row = SlackDestination(
        user_id=user.id,
        name=body.name.strip(),
        webhook_url_encrypted=encrypted,
        channel_hint=(body.channel_hint or None),
        events_json=events,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=f"could not save: {e}") from e
    await session.refresh(row)
    logger.info(
        "slack destination created id=%s user_id=%s", row.id, user.id
    )
    return _serialize(row)


@router.patch("/destinations/{dest_id}", response_model=DestinationOut)
async def update_destination(
    dest_id: int,
    body: UpdateDestinationBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> DestinationOut:
    row = await session.get(SlackDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    if body.name is not None:
        row.name = body.name.strip()
    if body.channel_hint is not None:
        row.channel_hint = body.channel_hint.strip() or None
    if body.events is not None:
        row.events_json = _clean_events(body.events)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/destinations/{dest_id}", status_code=204)
async def delete_destination(
    dest_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> None:
    row = await session.get(SlackDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    await session.delete(row)
    await session.commit()


class TestResult(BaseModel):
    ok: bool
    status_code: int | None
    detail: str | None


@router.post("/destinations/{dest_id}/test", response_model=TestResult)
async def test_destination(
    dest_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TestResult:
    """POST a short sample message to the webhook to confirm setup is
    correct. This bypasses the notifier's card-based message builder
    because we don't want to require a real card to test."""
    row = await session.get(SlackDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    try:
        webhook_url = crypto.decrypt(row.webhook_url_encrypted)
    except crypto.DecryptionFailed as e:
        raise HTTPException(status_code=500, detail="could not decrypt webhook") from e
    payload = {
        "text": "bugsift test ping",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🔔 bugsift test ping"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "If you can see this message, bugsift can deliver "
                        "Slack notifications for triage cards to this "
                        "webhook."
                    ),
                },
            },
        ],
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
    except httpx.HTTPError as e:
        return TestResult(ok=False, status_code=None, detail=str(e))
    ok = 200 <= response.status_code < 300
    return TestResult(
        ok=ok,
        status_code=response.status_code,
        detail=None if ok else response.text[:300],
    )


def _serialize(row: SlackDestination) -> DestinationOut:
    events = (
        dict(row.events_json) if isinstance(row.events_json, dict) else {}
    )
    # Ensure every known event name appears in the response even if the
    # stored flag set is missing it — the UI can render a checkbox row
    # without special-casing.
    for name in notifier.EVENTS:
        events.setdefault(name, notifier.DEFAULT_EVENTS.get(name, False))
    return DestinationOut(
        id=row.id,
        name=row.name,
        channel_hint=row.channel_hint,
        webhook_hint=_hint_from_url(row.webhook_url_encrypted),
        events=events,
        created_at=row.created_at,
    )


def _hint_from_url(encrypted: bytes) -> str:
    """Identifier-only hint. The Slack webhook URL is itself the auth
    token, so we deliberately reveal no substring of the secret part.
    Instead we derive a stable short fingerprint from the full URL —
    two rows with different secrets are distinguishable in the UI,
    but neither fingerprint helps an attacker reconstruct the secret.
    """
    try:
        url = crypto.decrypt(encrypted)
    except crypto.DecryptionFailed:
        return "••••"
    import hashlib
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"hook:{digest}"


def _clean_events(raw: dict[str, bool] | None) -> dict[str, bool]:
    if not raw:
        # Empty input falls back to notifier defaults so the user isn't
        # silent until they pick a flag.
        return dict(notifier.DEFAULT_EVENTS)
    out: dict[str, bool] = {}
    for name in notifier.EVENTS:
        out[name] = bool(raw.get(name, notifier.DEFAULT_EVENTS.get(name, False)))
    return out
