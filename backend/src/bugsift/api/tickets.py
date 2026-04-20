"""CRUD for ticket destinations — where approved feedback lands.

Provider-agnostic router; v1 implements Jira. Each destination stores
an encrypted API token + provider-specific config (for Jira: site URL,
user email, default project key + issue type). Creating a destination
validates the credentials against the provider's API first, so the
user finds out immediately if the token is bad — no "save succeeded,
approve fails later with 403" surprise.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import TicketDestination, User
from bugsift.security import crypto
from bugsift.tickets.jira import JiraAuthError, JiraClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])

Provider = Literal["jira"]


class JiraConfig(BaseModel):
    site_url: str = Field(min_length=5, max_length=255)
    user_email: str = Field(min_length=3, max_length=255)
    default_project_key: str = Field(min_length=1, max_length=32)
    default_issue_type: str = Field(default="Bug", max_length=64)


class CreateDestinationBody(BaseModel):
    provider: Provider
    name: str = Field(min_length=1, max_length=120)
    auth_token: str = Field(min_length=6, max_length=512)
    jira: JiraConfig | None = None


class UpdateDestinationBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_project_key: str | None = Field(default=None, min_length=1, max_length=32)
    default_issue_type: str | None = Field(default=None, max_length=64)


class DestinationOut(BaseModel):
    id: int
    provider: str
    name: str
    site_url: str | None
    user_email: str | None
    default_project_key: str | None
    default_issue_type: str | None
    token_hint: str
    created_at: datetime


class JiraProjectOut(BaseModel):
    id: str
    key: str
    name: str


@router.get("/destinations", response_model=list[DestinationOut])
async def list_destinations(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[DestinationOut]:
    rows = (
        await session.execute(
            select(TicketDestination)
            .where(TicketDestination.user_id == user.id)
            .order_by(TicketDestination.created_at.desc())
        )
    ).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("/destinations", response_model=DestinationOut, status_code=201)
async def create_destination(
    body: CreateDestinationBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DestinationOut:
    if body.provider == "jira":
        if body.jira is None:
            raise HTTPException(
                status_code=400, detail="jira provider requires a 'jira' config"
            )
        site_url = body.jira.site_url.strip().rstrip("/")
        if not site_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail="site_url must start with http:// or https://",
            )
        # Probe credentials before persisting; fail fast on bad tokens.
        client = JiraClient(
            site_url=site_url,
            user_email=body.jira.user_email.strip(),
            api_token=body.auth_token.strip(),
        )
        try:
            await client.validate()
        except JiraAuthError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"could not reach Jira: {e}"
            ) from e
        config = {
            "site_url": site_url,
            "user_email": body.jira.user_email.strip(),
            "default_project_key": body.jira.default_project_key.strip(),
            "default_issue_type": body.jira.default_issue_type.strip() or "Bug",
        }
    else:  # pragma: no cover — literal guard
        raise HTTPException(
            status_code=400, detail=f"unsupported provider {body.provider}"
        )

    try:
        encrypted = crypto.encrypt(body.auth_token.strip())
    except crypto.EncryptionKeyMissing as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    row = TicketDestination(
        user_id=user.id,
        provider=body.provider,
        name=body.name.strip(),
        auth_token_encrypted=encrypted,
        config_json=config,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=400, detail=f"could not save destination: {e}"
        ) from e
    await session.refresh(row)
    logger.info(
        "ticket destination created id=%s user_id=%s provider=%s",
        row.id,
        user.id,
        row.provider,
    )
    return _serialize(row)


@router.patch("/destinations/{dest_id}", response_model=DestinationOut)
async def update_destination(
    dest_id: int,
    body: UpdateDestinationBody,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DestinationOut:
    row = await session.get(TicketDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    config = dict(row.config_json or {})
    if body.name is not None:
        row.name = body.name.strip()
    if body.default_project_key is not None:
        config["default_project_key"] = body.default_project_key.strip()
    if body.default_issue_type is not None:
        config["default_issue_type"] = body.default_issue_type.strip() or "Bug"
    row.config_json = config
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/destinations/{dest_id}", status_code=204)
async def delete_destination(
    dest_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    row = await session.get(TicketDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    await session.delete(row)
    await session.commit()


@router.get(
    "/destinations/{dest_id}/projects", response_model=list[JiraProjectOut]
)
async def list_projects(
    dest_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[JiraProjectOut]:
    """Enumerate projects visible to the token — lets the UI show a
    dropdown instead of making the user type a project key."""
    row = await session.get(TicketDestination, dest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="destination not found")
    if row.provider != "jira":
        return []
    try:
        token = crypto.decrypt(row.auth_token_encrypted)
    except crypto.DecryptionFailed as e:
        raise HTTPException(status_code=500, detail="could not decrypt token") from e
    config = row.config_json or {}
    client = JiraClient(
        site_url=str(config.get("site_url") or ""),
        user_email=str(config.get("user_email") or ""),
        api_token=token,
    )
    try:
        projects = await client.list_projects()
    except JiraAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return [
        JiraProjectOut(id=p.id, key=p.key, name=p.name) for p in projects
    ]


def _serialize(row: TicketDestination) -> DestinationOut:
    config = row.config_json or {}
    try:
        token_hint = crypto.mask_key(crypto.decrypt(row.auth_token_encrypted))
    except crypto.DecryptionFailed:
        token_hint = "••••••••"
    return DestinationOut(
        id=row.id,
        provider=row.provider,
        name=row.name,
        site_url=config.get("site_url"),
        user_email=config.get("user_email"),
        default_project_key=config.get("default_project_key"),
        default_issue_type=config.get("default_issue_type"),
        token_hint=token_hint,
        created_at=row.created_at,
    )
