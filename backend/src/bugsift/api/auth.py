from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_optional_user, get_session
from bugsift.config import get_settings
from bugsift.db.models import Installation, User, UserApiKey
from bugsift.github import config as app_config
from bugsift.github import oauth as github_oauth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_STATE_KEY = "oauth_state"


class MeResponse(BaseModel):
    id: int
    github_id: int
    github_login: str
    email: str | None


@router.get("/github/start")
async def github_start(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    cfg = await app_config.load_app_config(session)
    settings = get_settings()
    if cfg is None:
        # Legacy env path — keep 503 with hint for operators who still configure by hand.
        if not settings.oauth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "GitHub OAuth is not configured. Register the App from the "
                    "onboarding wizard, or set GITHUB_APP_CLIENT_ID and "
                    "GITHUB_APP_CLIENT_SECRET in .env."
                ),
            )
        client_id = settings.github_app_client_id
    else:
        client_id = cfg.client_id
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_STATE_KEY] = state
    url = github_oauth.build_authorize_url_for(
        client_id=client_id,
        redirect_uri=settings.oauth_callback_url,
        state=state,
    )
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    settings = get_settings()
    expected_state = request.session.pop(OAUTH_STATE_KEY, None)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oauth state mismatch")

    cfg = await app_config.load_app_config(session)
    client_id = cfg.client_id if cfg else settings.github_app_client_id
    client_secret = cfg.client_secret if cfg else settings.github_app_client_secret
    token = await github_oauth.exchange_code_for_token_direct(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=settings.oauth_callback_url,
    )
    gh_user = await github_oauth.fetch_user(token)

    user = (
        await session.execute(select(User).where(User.github_id == gh_user.id))
    ).scalar_one_or_none()
    if user is None:
        user = User(github_id=gh_user.id, github_login=gh_user.login, email=gh_user.email)
        session.add(user)
    else:
        user.github_login = gh_user.login
        if gh_user.email:
            user.email = gh_user.email
    await session.commit()
    await session.refresh(user)

    request.session["user_id"] = user.id
    logger.info("login: user_id=%s github_login=%s", user.id, user.github_login)
    # First-time users (no installation or no LLM key) land on the wizard;
    # everyone else goes straight to the queue. The dashboard banner still
    # handles edge cases and gives returning users a manual path back to
    # onboarding whenever they want it.
    target = await _post_login_target(session, user.id)
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


async def _post_login_target(session: AsyncSession, user_id: int) -> str:
    install_count = (
        await session.execute(
            select(Installation.id).where(Installation.user_id == user_id).limit(1)
        )
    ).first()
    if install_count is None:
        return "/onboarding"
    key_count = (
        await session.execute(
            select(UserApiKey.id).where(UserApiKey.user_id == user_id).limit(1)
        )
    ).first()
    if key_count is None:
        return "/onboarding"
    return "/dashboard"


@router.get("/me", response_model=MeResponse | None)
async def me(user: User | None = Depends(get_optional_user)) -> MeResponse | None:
    if user is None:
        return None
    return MeResponse(id=user.id, github_id=user.github_id, github_login=user.github_login, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, _: User = Depends(get_current_user)) -> None:
    request.session.clear()
