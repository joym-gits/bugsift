"""CRUD for operator-defined routing rules.

Admin-only. Rules are scoped per-owner (``user_id``) so multi-tenant
deployments don't leak rules across accounts. Match / action payloads
are validated structurally on write so typos fail early instead of
silently never matching.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.audit.log import record as audit_record
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import TriageRule, User
from bugsift.rules.engine import (
    _ALLOWED_ACTION_KEYS,  # re-used for validation
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rules", tags=["rules"])


_ALLOWED_MATCH_KEYS = {
    "classification",
    "severity",
    "source",
    "repo_full_name_glob",
    "reproduction_verdict",
    "has_regression_suspects",
    "min_confidence",
    "proposed_action",
}


class RuleOut(BaseModel):
    id: int
    name: str
    enabled: bool
    priority: int
    match: dict[str, Any]
    action: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RuleCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=9999)
    match: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)


class RuleUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=9999)
    match: dict[str, Any] | None = None
    action: dict[str, Any] | None = None


def _serialize(row: TriageRule) -> RuleOut:
    return RuleOut(
        id=row.id,
        name=row.name,
        enabled=row.enabled,
        priority=row.priority,
        match=row.match_json or {},
        action=row.action_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_match(match: dict[str, Any]) -> None:
    for key in match.keys():
        if key not in _ALLOWED_MATCH_KEYS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown match key '{key}'. Allowed: "
                    + ", ".join(sorted(_ALLOWED_MATCH_KEYS))
                ),
            )


def _validate_action(action: dict[str, Any]) -> None:
    if not action:
        raise HTTPException(
            status_code=400,
            detail=(
                "action must specify at least one of: "
                + ", ".join(sorted(_ALLOWED_ACTION_KEYS))
            ),
        )
    for key in action.keys():
        if key not in _ALLOWED_ACTION_KEYS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown action key '{key}'. Allowed: "
                    + ", ".join(sorted(_ALLOWED_ACTION_KEYS))
                ),
            )


@router.get("", response_model=list[RuleOut])
async def list_rules(
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(Role.admin)),
) -> list[RuleOut]:
    rows = (
        await session.execute(
            select(TriageRule)
            .where(TriageRule.user_id == admin.id)
            .order_by(TriageRule.priority.asc(), TriageRule.id.asc())
        )
    ).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(
    body: RuleCreateBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(Role.admin)),
) -> RuleOut:
    _validate_match(body.match)
    _validate_action(body.action)
    row = TriageRule(
        user_id=admin.id,
        name=body.name.strip(),
        enabled=body.enabled,
        priority=body.priority,
        match_json=body.match,
        action_json=body.action,
    )
    session.add(row)
    await session.flush()
    await audit_record(
        session,
        actor=admin,
        action="rule.created",
        target_type="rule",
        target_id=row.id,
        summary=f"created rule '{row.name}'",
        metadata={"match": row.match_json, "action": row.action_json},
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: int,
    body: RuleUpdateBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(Role.admin)),
) -> RuleOut:
    row = await session.get(TriageRule, rule_id)
    if row is None or row.user_id != admin.id:
        raise HTTPException(status_code=404, detail="rule not found")
    before = {
        "name": row.name,
        "enabled": row.enabled,
        "priority": row.priority,
        "match": row.match_json,
        "action": row.action_json,
    }
    if body.name is not None:
        row.name = body.name.strip()
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.priority is not None:
        row.priority = body.priority
    if body.match is not None:
        _validate_match(body.match)
        row.match_json = body.match
    if body.action is not None:
        _validate_action(body.action)
        row.action_json = body.action
    await audit_record(
        session,
        actor=admin,
        action="rule.updated",
        target_type="rule",
        target_id=row.id,
        summary=f"updated rule '{row.name}'",
        metadata={"before": before},
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role(Role.admin)),
) -> None:
    row = await session.get(TriageRule, rule_id)
    if row is None or row.user_id != admin.id:
        raise HTTPException(status_code=404, detail="rule not found")
    await audit_record(
        session,
        actor=admin,
        action="rule.deleted",
        target_type="rule",
        target_id=row.id,
        summary=f"deleted rule '{row.name}'",
        request=request,
    )
    await session.delete(row)
    await session.commit()
