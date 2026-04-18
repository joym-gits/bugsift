from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import User
from bugsift.db.session import SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = await session.get(User, user_id)
    if not user:
        # Stale session (user deleted).
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return await session.get(User, user_id)
