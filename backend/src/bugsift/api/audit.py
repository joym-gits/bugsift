"""Read API for the audit log (admin-only).

JSON list for the dashboard and a CSV export for compliance folks who
want to diff against their SIEM. Every row is append-only on the write
path; there is no update or delete endpoint on purpose.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import AuditEvent, User

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    actor_user_id: int | None
    actor_login: str
    action: str
    target_type: str
    target_id: str | None
    summary: str
    metadata: dict[str, Any] | None
    request_ip: str | None
    request_ua: str | None
    created_at: datetime


def _serialize(row: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        actor_user_id=row.actor_user_id,
        actor_login=row.actor_login,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        summary=row.summary,
        metadata=row.metadata_json,
        request_ip=row.request_ip,
        request_ua=row.request_ua,
        created_at=row.created_at,
    )


@router.get("", response_model=list[AuditEventOut])
async def list_events(
    actor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(Role.admin)),
) -> list[AuditEventOut]:
    limit = max(1, min(limit, 1000))
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if actor:
        stmt = stmt.where(AuditEvent.actor_login == actor)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if target_type:
        stmt = stmt.where(AuditEvent.target_type == target_type)
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/export.csv")
async def export_csv(
    actor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(Role.admin)),
) -> StreamingResponse:
    """Stream the matching events as CSV. No hard limit — the audit log
    is the source of truth, so an export needs to be complete."""
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.asc())
    if actor:
        stmt = stmt.where(AuditEvent.actor_login == actor)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if target_type:
        stmt = stmt.where(AuditEvent.target_type == target_type)
    rows = (await session.execute(stmt)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id",
        "created_at",
        "actor_login",
        "actor_user_id",
        "action",
        "target_type",
        "target_id",
        "summary",
        "request_ip",
        "request_ua",
        "metadata_json",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.created_at.isoformat(),
            r.actor_login,
            r.actor_user_id or "",
            r.action,
            r.target_type,
            r.target_id or "",
            r.summary,
            r.request_ip or "",
            r.request_ua or "",
            "" if r.metadata_json is None else str(r.metadata_json),
        ])
    buf.seek(0)
    filename = f"bugsift-audit-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/actions", response_model=list[str])
async def list_known_actions(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(Role.admin)),
) -> list[str]:
    """Distinct actions seen in the log — used to populate a filter dropdown."""
    rows = (
        await session.execute(
            select(AuditEvent.action).distinct().order_by(AuditEvent.action.asc())
        )
    ).all()
    return [r[0] for r in rows]
