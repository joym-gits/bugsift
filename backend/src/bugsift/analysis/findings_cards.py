"""Materialize analyzer.Finding objects into TriageCard rows.

Deliberately bypasses agent.orchestrator/compute_severity — there is
no live issue to classify, dedup against GitHub issues, or reproduce
in a sandbox for a static-analysis finding; running the full pipeline
would be both semantically wrong and a wasted LLM budget. Severity
comes directly from the findings LLM pass (see
:mod:`bugsift.analysis.analyzer`).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from sqlalchemy import select

from bugsift.analysis.analyzer import Finding
from bugsift.db.models import Repo, TriageCard

logger = logging.getLogger(__name__)


def finding_key(repo_id: int, branch: str, finding: Finding) -> str:
    """Deterministic fingerprint so re-running analysis on unchanged
    code doesn't spam duplicate cards. No LLM/embedding needed (unlike
    feedback's semantic near-dup collapsing) — re-analysis of the same
    code should reproduce ~the same finding, so a cheap fingerprint on
    (repo, branch, title, primary file) is enough to skip re-inserting
    it."""
    primary_file = finding.files[0].file_path if finding.files else ""
    basis = f"{repo_id}:{branch}:{finding.title.strip().lower()}:{primary_file}"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


async def write_finding_cards(
    session, *, repo: Repo, branch: str, findings: list[Finding]
) -> list[TriageCard]:
    """Insert one TriageCard per new finding; skip ones whose
    ``finding_key`` already exists for this repo (idempotent
    re-analysis). Returns only the newly-inserted cards."""
    if not findings:
        return []

    keyed = [(f, finding_key(repo.id, branch, f)) for f in findings]
    existing_keys = set(
        (
            await session.execute(
                select(TriageCard.finding_key).where(
                    TriageCard.repo_id == repo.id,
                    TriageCard.source == "analysis",
                    TriageCard.finding_key.in_([k for _, k in keyed]),
                )
            )
        )
        .scalars()
        .all()
    )

    cards: list[TriageCard] = []
    for finding, key in keyed:
        if key in existing_keys:
            continue
        card = TriageCard(
            repo_id=repo.id,
            source="analysis",
            issue_number=None,
            status="pending",
            classification="bug",
            finding_category=finding.category,
            severity=finding.severity,
            confidence=Decimal(f"{finding.confidence:.3f}"),
            rationale=finding.description,
            suspected_files_json=(
                [
                    {
                        "file_path": f.file_path,
                        "line_range": f.line_range,
                        "rationale": f.rationale,
                    }
                    for f in finding.files
                ]
                or None
            ),
            finding_key=key,
            draft_comment=finding.title,
            raw_payload_json={"title": finding.title, "branch": branch},
        )
        session.add(card)
        cards.append(card)
        logger.info(
            "analysis finding card queued repo=%s branch=%s title=%s severity=%s",
            repo.full_name,
            branch,
            finding.title,
            finding.severity,
        )
    return cards
