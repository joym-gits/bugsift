from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
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
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
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

    row = UserApiKey(
        user_id=user.id,
        provider=body.provider,
        encrypted_key=crypto.encrypt(body.key),
        masked_hint=crypto.mask_key(body.key),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return KeyResponse(id=row.id, provider=row.provider, masked_hint=row.masked_hint, created_at=row.created_at)  # type: ignore[arg-type]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    row = await session.get(UserApiKey, key_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    await session.delete(row)
    await session.commit()
