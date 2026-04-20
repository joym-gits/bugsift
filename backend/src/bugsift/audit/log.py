"""Append-only audit logger.

Call :func:`record` from any route that mutates security- or ops-
relevant state. The helper never raises — if writing the audit row
fails (DB down, constraint violation), we log a warning and continue;
failing a user action because we couldn't log it is worse than
missing one line in the trail.

All writes go through this helper so we have exactly one place to
audit the audit logger.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import AuditEvent, User

logger = logging.getLogger(__name__)


# Canonical action constants. Keep the set small and stable — the
# ``/audit`` UI filters on exact matches, so drift here is noisy.
class Action:
    USER_LOGIN = "user.login"
    USER_ROLE_CHANGED = "user.role_changed"
    CARD_APPROVED = "card.approved"
    CARD_SKIPPED = "card.skipped"
    CARD_EDITED = "card.edited"
    CARD_RERUN = "card.rerun"
    KEY_CREATED = "key.created"
    KEY_DELETED = "key.deleted"
    APP_REGISTERED = "github_app.registered"
    APP_DELETED = "github_app.deleted"
    INSTALLATION_LINKED = "installation.linked"
    DESTINATION_CREATED = "destination.created"
    DESTINATION_DELETED = "destination.deleted"
    SLACK_CREATED = "slack.created"
    SLACK_DELETED = "slack.deleted"
    FEEDBACK_APP_CREATED = "feedback_app.created"
    FEEDBACK_APP_UPDATED = "feedback_app.updated"
    FEEDBACK_APP_DELETED = "feedback_app.deleted"


async def record(
    session: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: str | int | None,
    summary: str,
    actor: User | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Write one audit row. Best-effort; swallows errors."""
    try:
        ip, ua = _request_fingerprint(request)
        row = AuditEvent(
            actor_user_id=(actor.id if actor else None),
            actor_login=(actor.github_login if actor else "system"),
            action=action,
            target_type=target_type,
            target_id=(str(target_id) if target_id is not None else None),
            summary=summary[:256],
            metadata_json=metadata,
            request_ip=ip,
            request_ua=ua,
        )
        session.add(row)
        # Flush (not commit) so this row rides along with whatever
        # transaction the caller is running — approve-and-audit then
        # succeed or fail together.
        await session.flush()
    except Exception:  # pragma: no cover — resilience path
        logger.exception(
            "audit: failed to record action=%s target=%s:%s",
            action,
            target_type,
            target_id,
        )


def _request_fingerprint(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    # Prefer X-Real-IP (nginx injects it) so rate-limit and audit IPs
    # match; fall back to the socket peer.
    ip = request.headers.get("x-real-ip") or (
        request.client.host if request.client else None
    )
    ua = request.headers.get("user-agent")
    if ua:
        ua = ua[:256]
    return ip, ua
