"""Admin user-management.

Admins can list every user on the deployment and change any user's
role. The last admin can't demote themselves — preventing the
"accidentally locked everyone out of the admin-only pages" shape
that enterprise buyers always ask about.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Request

from bugsift.api.deps import get_session
from bugsift.audit.log import Action, record as audit_record
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: int
    github_login: str
    email: str | None
    role: str
    created_at: datetime


class UpdateRoleBody(BaseModel):
    role: str


@router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(Role.admin)),
) -> list[UserOut]:
    rows = (
        await session.execute(select(User).order_by(User.created_at.asc()))
    ).scalars().all()
    return [
        UserOut(
            id=u.id,
            github_login=u.github_login,
            email=u.email,
            role=u.role,
            created_at=u.created_at,
        )
        for u in rows
    ]


@router.patch("/{user_id}/role", response_model=UserOut)
async def update_role(
    user_id: int,
    body: UpdateRoleBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(Role.admin)),
) -> UserOut:
    try:
        new_role = Role(body.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of: {', '.join(r.value for r in Role)}",
        )

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    # Can't demote yourself if you're the only admin — otherwise no one
    # can manage users / rotate keys / register GitHub Apps afterward.
    if target.id == admin.id and new_role != Role.admin:
        admin_count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.role == Role.admin.value)
            )
        ).scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "You're the only admin on this deployment. Promote someone "
                    "else first, then demote yourself."
                ),
            )

    prev_role = target.role
    target.role = new_role.value
    await audit_record(
        session,
        actor=admin,
        action=Action.USER_ROLE_CHANGED,
        target_type="user",
        target_id=target.id,
        summary=f"{target.github_login}: {prev_role} → {target.role}",
        metadata={"target_login": target.github_login, "before": prev_role, "after": target.role},
        request=request,
    )
    await session.commit()
    await session.refresh(target)
    logger.info(
        "role change: actor_id=%s target_id=%s new_role=%s",
        admin.id,
        target.id,
        target.role,
    )
    return UserOut(
        id=target.id,
        github_login=target.github_login,
        email=target.email,
        role=target.role,
        created_at=target.created_at,
    )
