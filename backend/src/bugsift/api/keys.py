from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.audit.log import Action, record as audit_record
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import User, UserApiKey
from bugsift.security import crypto

router = APIRouter(prefix="/keys", tags=["keys"])

Provider = Literal["anthropic", "openai", "google", "ollama"]


class KeyResponse(BaseModel):
    id: int
    provider: Provider
    masked_hint: str
    created_at: datetime


class KeyCreate(BaseModel):
    provider: Provider
    key: str = Field(min_length=1, max_length=512)


@router.get("", response_model=list[KeyResponse])
async def list_keys(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[KeyResponse]:
    rows = (
        await session.execute(
            select(UserApiKey).where(UserApiKey.user_id == user.id).order_by(UserApiKey.created_at.desc())
        )
    ).scalars().all()
    return [
        KeyResponse(id=r.id, provider=r.provider, masked_hint=r.masked_hint, created_at=r.created_at)  # type: ignore[arg-type]
        for r in rows
    ]


@router.post("", response_model=KeyResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: KeyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> KeyResponse:
    existing = (
        await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user.id, UserApiKey.provider == body.provider
            )
        )
    ).scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.flush()

    try:
        encrypted = crypto.encrypt(body.key)
    except crypto.EncryptionKeyMissing as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    row = UserApiKey(
        user_id=user.id,
        provider=body.provider,
        encrypted_key=encrypted,
        masked_hint=crypto.mask_key(body.key),
    )
    session.add(row)
    await session.flush()
    await audit_record(
        session,
        actor=user,
        action=Action.KEY_CREATED,
        target_type="key",
        target_id=row.id,
        summary=f"added {body.provider} API key",
        metadata={"provider": body.provider, "masked_hint": row.masked_hint},
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return KeyResponse(id=row.id, provider=row.provider, masked_hint=row.masked_hint, created_at=row.created_at)  # type: ignore[arg-type]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(Role.triager)),
) -> None:
    row = await session.get(UserApiKey, key_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    await audit_record(
        session,
        actor=user,
        action=Action.KEY_DELETED,
        target_type="key",
        target_id=row.id,
        summary=f"deleted {row.provider} API key",
        metadata={"provider": row.provider},
        request=request,
    )
    await session.delete(row)
    await session.commit()
