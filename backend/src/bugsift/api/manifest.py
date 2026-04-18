"""One-click GitHub App registration via the manifest flow.

The maintainer clicks "Create bugsift GitHub App" in the onboarding wizard.
The frontend hits ``POST /github/app/manifest/start`` which returns an HTML
form that auto-POSTs to ``github.com/settings/apps/new`` with a pre-filled
manifest. GitHub creates the App, redirects back to our callback with a
temporary ``code``; we exchange it for the real credentials and store them
in the ``github_app_credentials`` singleton.

The webhook URL still needs a public-reachable tunnel (smee, cloudflared,
ngrok). The wizard explains this and gives the user the exact smee command
to run.
"""

from __future__ import annotations

import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.config import get_settings
from bugsift.db.models import GithubAppCredentials, User
from bugsift.github import config as app_config
from bugsift.github import smee
from bugsift.security import crypto

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/github/app/manifest", tags=["onboarding"])

SESSION_STATE_KEY = "manifest_state"
SESSION_WEBHOOK_URL_KEY = "manifest_webhook_url"


class StartRequest(BaseModel):
    # Optional — leave blank and bugsift auto-provisions a smee.io channel
    # and forwards it in-process so the operator never sees a terminal.
    webhook_url: HttpUrl | None = None
    app_name_suffix: str | None = None


class AppConfigStatus(BaseModel):
    configured: bool
    name: str | None = None
    slug: str | None = None
    html_url: str | None = None
    tunnel_url: str | None = None
    tunnel_running: bool = False


class StartResponse(BaseModel):
    github_url: str
    manifest: dict
    state: str


# First-run operator access model: the manifest flow is unauthenticated
# *only while no App exists yet*. In a self-hosted deployment, whoever
# can reach the server before onboarding is the operator — there's no
# one else to authenticate. Once an App is registered, these endpoints
# flip back to requiring a logged-in user (and delete requires auth),
# so a drive-by visitor can't hijack the deployment later.


@router.get("/status", response_model=AppConfigStatus)
async def app_status(
    session: AsyncSession = Depends(get_session),
) -> AppConfigStatus:
    """Public: the landing page reads this before deciding what to show."""
    cfg = await app_config.load_app_config(session)
    tunnel_status = smee.forwarder_status()
    base = dict(
        tunnel_url=tunnel_status.get("tunnel_url") or await smee.get_tunnel_url(),
        tunnel_running=bool(tunnel_status.get("running")),
    )
    if cfg is None:
        return AppConfigStatus(configured=False, **base)
    return AppConfigStatus(
        configured=True,
        name=cfg.name,
        slug=cfg.slug,
        html_url=cfg.html_url,
        **base,
    )


@router.post("/start", response_model=StartResponse)
async def start(
    request: Request,
    body: StartRequest,
    session: AsyncSession = Depends(get_session),
) -> StartResponse:
    """Prepare the manifest + state; let the frontend submit its own form.

    The earlier version returned an HTML ``<form>`` that auto-submitted
    from an ``about:blank`` document; that lost third-party cookie
    behaviour in some browsers (incognito especially), which made GitHub
    500 when it couldn't identify the authenticated user. Returning JSON
    and letting the bugsift page build a native form side-steps the issue.
    """
    existing = await app_config.load_app_config(session)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A GitHub App is already registered with this deployment. "
                "Sign in, go to Settings, and delete it first if you want to "
                "re-register."
            ),
        )
    settings = get_settings()
    webhook_url = str(body.webhook_url) if body.webhook_url else await smee.ensure_tunnel_url()
    await smee.start_forwarder(webhook_url)

    state = secrets.token_urlsafe(32)
    request.session[SESSION_STATE_KEY] = state
    request.session[SESSION_WEBHOOK_URL_KEY] = webhook_url

    manifest = _build_manifest(
        public_url=settings.public_url,
        webhook_url=webhook_url,
        suffix=body.app_name_suffix or _default_suffix(settings.public_url),
    )
    return StartResponse(
        github_url=f"https://github.com/settings/apps/new?state={state}",
        manifest=manifest,
        state=state,
    )


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Anonymous — matches the POST /start that kicked the flow off. The
    CSRF state-token in the session is the authorisation signal here."""
    expected_state = request.session.pop(SESSION_STATE_KEY, None)
    request.session.pop(SESSION_WEBHOOK_URL_KEY, None)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="manifest state mismatch"
        )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app-manifests/{code}/conversions",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )
    if response.status_code != 201:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"github code exchange failed: {response.status_code} {response.text[:200]}",
        )
    payload = response.json()

    try:
        await _persist_credentials(session, payload)
    except crypto.EncryptionKeyMissing as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    app_config.clear_cache()
    logger.info(
        "github app registered via manifest: id=%s slug=%s",
        payload.get("id"),
        payload.get("slug"),
    )
    return RedirectResponse("/onboarding?step=install", status_code=303)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_app(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> None:
    """Wipe the stored App. Useful for re-registering against a new tunnel."""
    row = (
        await session.execute(select(GithubAppCredentials).where(GithubAppCredentials.id == 1))
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
    app_config.clear_cache()


def _build_manifest(*, public_url: str, webhook_url: str, suffix: str) -> dict:
    base = public_url.rstrip("/")
    return {
        "name": f"bugsift-{suffix}"[:34],  # GitHub App names are limited
        "url": base,
        "hook_attributes": {"url": webhook_url, "active": True},
        "redirect_url": f"{base}/api/github/app/manifest/callback",
        "callback_urls": [f"{base}/api/auth/github/callback"],
        "setup_url": f"{base}/api/github/install/callback",
        "setup_on_update": False,
        "public": False,
        "default_permissions": {
            "issues": "write",
            "contents": "read",
            "metadata": "read",
            "pull_requests": "read",
        },
        "default_events": ["issues", "issue_comment", "push"],
    }


def _default_suffix(public_url: str) -> str:
    """Fallback App-name slug when the caller doesn't provide one.

    We avoid global uniqueness collisions by mixing in a short random tag.
    """
    host_part = public_url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
    safe = "".join(c if c.isalnum() else "-" for c in host_part).strip("-") or "local"
    return f"{safe}-{secrets.token_hex(3)}"


async def _persist_credentials(session: AsyncSession, payload: dict) -> None:
    existing = (
        await session.execute(select(GithubAppCredentials).where(GithubAppCredentials.id == 1))
    ).scalar_one_or_none()
    fields = dict(
        github_app_id=int(payload["id"]),
        slug=str(payload.get("slug") or ""),
        name=str(payload.get("name") or ""),
        owner_login=str((payload.get("owner") or {}).get("login", "")),
        html_url=str(payload.get("html_url") or ""),
        client_id=str(payload["client_id"]),
        client_secret_encrypted=crypto.encrypt(str(payload["client_secret"])),
        webhook_secret_encrypted=crypto.encrypt(str(payload["webhook_secret"])),
        private_key_pem_encrypted=crypto.encrypt(str(payload["pem"])),
    )
    if existing is None:
        session.add(GithubAppCredentials(id=1, **fields))
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
    await session.commit()
