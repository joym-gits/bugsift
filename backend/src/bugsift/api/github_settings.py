"""Authenticated read endpoints for the GitHub-settings page.

Returns the persisted values the operator probably wants to see —
App name, slug, html_url, masked client id / secret, masked webhook
secret, PEM fingerprint, tunnel URL and forwarder health — without
exposing anything that would let a reader impersonate the App.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import GithubAppCredentials, Installation, Repo, User
from bugsift.github import smee
from bugsift.security import crypto

router = APIRouter(prefix="/github", tags=["github"])


class AppDetails(BaseModel):
    configured: bool
    github_app_id: int | None = None
    name: str | None = None
    slug: str | None = None
    owner_login: str | None = None
    html_url: str | None = None
    client_id: str | None = None
    client_secret_masked: str | None = None
    webhook_secret_masked: str | None = None
    private_key_fingerprint: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    tunnel_url: str | None = None
    tunnel_running: bool = False
    installations_count: int = 0
    repos_count: int = 0


class InstallationOut(BaseModel):
    id: int
    github_installation_id: int
    installed_at: datetime
    suspended_at: datetime | None = None
    repo_count: int = 0


@router.get("/app", response_model=AppDetails)
async def app_details(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AppDetails:
    """Returns persisted App configuration, secrets masked."""
    row = (
        await session.execute(
            select(GithubAppCredentials).where(GithubAppCredentials.id == 1)
        )
    ).scalar_one_or_none()

    tunnel_snapshot = smee.forwarder_status()
    base = AppDetails(
        configured=row is not None,
        tunnel_url=tunnel_snapshot.get("tunnel_url") or await smee.get_tunnel_url(),
        tunnel_running=bool(tunnel_snapshot.get("running")),
    )
    if row is None:
        return base

    # Per-user install + repo counts give the page something honest to show
    # without requiring the user to scroll through /api/repos separately.
    install_count = (
        await session.execute(
            select(func.count(Installation.id)).where(Installation.user_id == user.id)
        )
    ).scalar_one()
    repo_count = (
        await session.execute(
            select(func.count(Repo.id))
            .join(Installation, Repo.installation_id == Installation.id)
            .where(Installation.user_id == user.id)
        )
    ).scalar_one()

    return AppDetails(
        configured=True,
        github_app_id=row.github_app_id,
        name=row.name,
        slug=row.slug,
        owner_login=row.owner_login,
        html_url=row.html_url,
        client_id=row.client_id,
        client_secret_masked=_mask_bytes(row.client_secret_encrypted),
        webhook_secret_masked=_mask_bytes(row.webhook_secret_encrypted),
        private_key_fingerprint=_pem_fingerprint(row.private_key_pem_encrypted),
        created_at=row.created_at,
        updated_at=row.updated_at,
        tunnel_url=base.tunnel_url,
        tunnel_running=base.tunnel_running,
        installations_count=int(install_count or 0),
        repos_count=int(repo_count or 0),
    )


@router.get("/installations", response_model=list[InstallationOut])
async def list_installations(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[InstallationOut]:
    """Every installation this user has linked, with a repo-count per row."""
    rows = (
        await session.execute(
            select(
                Installation.id,
                Installation.github_installation_id,
                Installation.installed_at,
                Installation.suspended_at,
                func.count(Repo.id).label("repo_count"),
            )
            .join(Repo, Repo.installation_id == Installation.id, isouter=True)
            .where(Installation.user_id == user.id)
            .group_by(Installation.id)
            .order_by(Installation.installed_at.desc())
        )
    ).all()
    return [
        InstallationOut(
            id=r.id,
            github_installation_id=r.github_installation_id,
            installed_at=r.installed_at,
            suspended_at=r.suspended_at,
            repo_count=int(r.repo_count or 0),
        )
        for r in rows
    ]


def _mask_bytes(encrypted: bytes) -> str | None:
    """Decrypt, then show only the first 3 and last 4 characters.

    We don't return the raw secret — the masked form is for the operator
    to recognise which secret is installed, not to copy-paste anywhere.
    """
    if not encrypted:
        return None
    try:
        plaintext = crypto.decrypt(encrypted)
    except crypto.DecryptionFailed:
        return "<decryption failed>"
    return crypto.mask_key(plaintext)


def _pem_fingerprint(encrypted_pem: bytes) -> str | None:
    """SHA-256 fingerprint (first 16 hex chars) of the decrypted PEM.

    Enough to verify the stored key matches the one shown in GitHub's App
    settings page without exposing the PEM itself.
    """
    if not encrypted_pem:
        return None
    try:
        plaintext = crypto.decrypt(encrypted_pem)
    except crypto.DecryptionFailed:
        return "<decryption failed>"
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]


