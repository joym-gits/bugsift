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

import json
import logging
import secrets
from html import escape
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.config import get_settings
from bugsift.db.models import GithubAppCredentials, User
from bugsift.github import config as app_config
from bugsift.security import crypto

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/github/app/manifest", tags=["onboarding"])

SESSION_STATE_KEY = "manifest_state"
SESSION_WEBHOOK_URL_KEY = "manifest_webhook_url"


class StartRequest(BaseModel):
    webhook_url: HttpUrl
    app_name_suffix: str | None = None


class AppConfigStatus(BaseModel):
    configured: bool
    name: str | None = None
    slug: str | None = None
    html_url: str | None = None


@router.get("/status", response_model=AppConfigStatus)
async def app_status(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> AppConfigStatus:
    cfg = await app_config.load_app_config(session)
    if cfg is None:
        return AppConfigStatus(configured=False)
    return AppConfigStatus(
        configured=True, name=cfg.name, slug=cfg.slug, html_url=cfg.html_url
    )


@router.post("/start", response_class=HTMLResponse)
async def start(
    request: Request,
    body: StartRequest,
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    request.session[SESSION_STATE_KEY] = state
    request.session[SESSION_WEBHOOK_URL_KEY] = str(body.webhook_url)

    manifest = _build_manifest(
        public_url=settings.public_url,
        webhook_url=str(body.webhook_url),
        suffix=body.app_name_suffix or user.github_login,
    )
    # GitHub's manifest flow expects an HTML POST form to
    # https://github.com/settings/apps/new?state=... with a single
    # <input name="manifest"> containing the JSON manifest.
    form_action = f"https://github.com/settings/apps/new?state={quote(state)}"
    manifest_json = escape(json.dumps(manifest))
    html = (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<title>Creating GitHub App…</title>"
        "<style>body{font-family:system-ui;padding:4rem;text-align:center;color:#333}</style>"
        "</head><body>"
        "<p>Redirecting you to GitHub to create the bugsift App…</p>"
        f'<form id="f" method="post" action="{form_action}">'
        f'<input type="hidden" name="manifest" value=\'{manifest_json}\'>'
        "</form>"
        "<script>document.getElementById('f').submit();</script>"
        "</body></html>"
    )
    return HTMLResponse(html)


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
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
