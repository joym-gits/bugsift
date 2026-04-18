"""Authenticated GitHub App install callback.

When a user installs the GitHub App, GitHub redirects them here with
``installation_id``. We use this to associate the installation with the
currently-logged-in user — the webhook by itself doesn't know who did the
install. Idempotent: re-running it just refreshes the user link.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/github", tags=["github"])


@router.get("/install/callback")
async def install_callback(
    installation_id: int,
    setup_action: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    installation = (
        await session.execute(
            select(Installation).where(Installation.github_installation_id == installation_id)
        )
    ).scalar_one_or_none()

    if installation is None:
        installation = Installation(github_installation_id=installation_id, user_id=user.id)
        session.add(installation)
    else:
        installation.user_id = user.id

    await session.commit()
    logger.info(
        "install callback user_id=%s installation_id=%s action=%s",
        user.id,
        installation_id,
        setup_action,
    )
    return RedirectResponse("/dashboard", status_code=303)
