"""Fetch recent operator corrections so the orchestrator can learn
from them on the next triage run.

The hot path is one indexed query per triage job:
``(repo_id, classification, created_at DESC)``, capped at ``limit``.
Classification filter is *soft* — we prefer same-class corrections
but fall back to any-class if we'd otherwise return nothing.

Output is a list of :class:`CorrectionRef` objects the prompt
templates can render compactly; callers never see raw JSONB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import CardCorrection

MAX_RECENT_CORRECTIONS = 10


@dataclass(frozen=True)
class CorrectionRef:
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    issue_context: str | None
    classification: str | None

    def to_prompt_bullet(self) -> str:
        """Render a compact bullet for inclusion in a prompt.
        ``override_labels: ['bug'] → ['bug', 'needs-info']`` on issue
        *"Cannot login on Safari"*."""
        change = _describe_change(self.action, self.before, self.after)
        if self.issue_context:
            snippet = self.issue_context.replace("\n", " ")[:120]
            return f"- {change} — issue: “{snippet}”"
        return f"- {change}"


async def recent_corrections_for_repo(
    session: AsyncSession,
    repo_id: int,
    classification: str | None,
    *,
    limit: int = MAX_RECENT_CORRECTIONS,
) -> list[CorrectionRef]:
    """Return the most recent corrections for ``repo_id`` — filtered
    to the same ``classification`` when available, otherwise
    fallback-unfiltered (subject to ``limit``)."""
    if limit <= 0:
        return []

    if classification:
        matched = await _fetch(session, repo_id, classification, limit)
        if matched:
            return matched
    return await _fetch(session, repo_id, None, limit)


async def _fetch(
    session: AsyncSession,
    repo_id: int,
    classification: str | None,
    limit: int,
) -> list[CorrectionRef]:
    stmt = (
        select(CardCorrection)
        .where(CardCorrection.repo_id == repo_id)
        .order_by(desc(CardCorrection.created_at))
        .limit(limit)
    )
    if classification:
        stmt = stmt.where(CardCorrection.classification == classification)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        CorrectionRef(
            action=r.action,
            before=r.before_json,
            after=r.after_json,
            issue_context=r.issue_context,
            classification=r.classification,
        )
        for r in rows
    ]


def _describe_change(
    action: str, before: dict[str, Any] | None, after: dict[str, Any] | None
) -> str:
    if action == "override_assignees":
        b = (before or {}).get("assignees") or []
        a = (after or {}).get("assignees") or []
        return f"Operator reassigned: {_fmt_list(b)} → {_fmt_list(a)}"
    if action == "override_labels":
        b = (before or {}).get("labels") or []
        a = (after or {}).get("labels") or []
        return f"Operator relabeled: {_fmt_list(b)} → {_fmt_list(a)}"
    if action == "edit_comment":
        after_text = (after or {}).get("final_comment") or ""
        short = after_text.strip().replace("\n", " ")[:160]
        return f"Operator edited draft, final: “{short}”"
    if action == "reclassify":
        b = (before or {}).get("classification")
        a = (after or {}).get("classification")
        return f"Operator reclassified: {b} → {a}"
    if action == "skip":
        return "Operator skipped this card instead of approving"
    return f"Operator action: {action}"


def _fmt_list(xs: list[Any]) -> str:
    if not xs:
        return "—"
    return ", ".join(str(x) for x in xs)
