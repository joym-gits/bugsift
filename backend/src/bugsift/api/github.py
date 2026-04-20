"""Authenticated GitHub App install callback.

When a user installs the GitHub App, GitHub redirects them here with
``installation_id``. We use this to associate the installation with the
currently-logged-in user — the webhook by itself doesn't know who did the
install. Idempotent: re-running it just refreshes the user link.

**Security (C1).** GitHub's install flow doesn't round-trip a CSRF token
we control, so we verify ownership server-side instead:

- If the installation row already exists in our DB with a non-null
  ``user_id`` that isn't the current user, refuse. This blocks the
  "swap owner via crafted link" attack.
- Otherwise we fetch the installation's metadata from GitHub (App JWT)
  and require that, for a User-target installation, ``account.login``
  matches the authenticated user's GitHub login. Organization-target
  installations already require org-admin rights on GitHub's side to
  create, so we trust that gate for first-link.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import Installation, User
from bugsift.github import app as gh_app
from bugsift.github import config as app_config

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

    # Block the swap-owner CSRF: an existing row linked to someone else
    # must never be silently re-parented to the visitor.
    if (
        installation is not None
        and installation.user_id is not None
        and installation.user_id != user.id
    ):
        logger.warning(
            "install callback blocked: installation_id=%s already linked to user_id=%s, "
            "visitor=user_id=%s",
            installation_id,
            installation.user_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This installation is already linked to a different bugsift account. "
                "Sign in as the original installer, or remove the installation on "
                "GitHub and reinstall."
            ),
        )

    # For first-time links, verify ownership with GitHub directly. If the
    # App credentials aren't loadable we can't verify — refuse rather than
    # blindly trust the query string.
    if installation is None:
        cfg = await app_config.load_app_config(session)
        try:
            owner = await gh_app.get_installation_metadata(
                installation_id,
                app_id=cfg.app_id if cfg else None,
                private_key_pem=cfg.private_key_pem if cfg else None,
            )
        except gh_app.AppConfigError:
            logger.exception("install callback: App credentials unavailable")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App credentials not configured; cannot verify ownership.",
            )
        except Exception:
            logger.exception(
                "install callback: ownership lookup failed installation_id=%s",
                installation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not verify installation ownership with GitHub.",
            )

        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub does not recognise this installation id.",
            )

        # User-target installs must match the logged-in GitHub user.
        # Org-target installs are admitted because installing on an org
        # already requires org-admin on GitHub's side.
        if owner.target_type == "User" and owner.account_login.lower() != user.github_login.lower():
            logger.warning(
                "install callback blocked: installation_id=%s account=%s != user=%s",
                installation_id,
                owner.account_login,
                user.github_login,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This installation belongs to a different GitHub account. "
                    "Sign in as @" + owner.account_login + " to link it."
                ),
            )

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
