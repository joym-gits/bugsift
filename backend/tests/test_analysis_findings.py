"""Tests for the repo-analysis findings pass and its materialization
into TriageCard rows (source='analysis').

Covers:
- Findings parsing from a scripted LLM response (happy path).
- Malformed JSON degrades to an empty findings list, never raises.
- Citations to files that never appeared in the input summaries are
  dropped, but the finding itself is kept.
- write_finding_cards is idempotent — re-running analysis with the
  same findings doesn't create duplicate cards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from bugsift.analysis import analyzer as analyzer_mod
from bugsift.analysis.analyzer import DirectorySummary, FileSummary, Finding, FindingFile
from bugsift.analysis.findings_cards import finding_key, write_finding_cards
from bugsift.db.models import Installation, Repo, TriageCard, User
from bugsift.llm.base import LLMProvider, LLMResponse, Usage


@dataclass
class _ScriptedProvider(LLMProvider):
    responses: list[str]
    name: str = "stub"

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        if not self.responses:
            raise RuntimeError("scripted provider ran out of responses")
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model="stub-model",
            usage=Usage(prompt_tokens=10, completion_tokens=10, cost_usd=0.01),
        )

    async def embed(self, text, *, model=None):
        raise NotImplementedError


def _dirs() -> list[DirectorySummary]:
    return [
        DirectorySummary(
            path="backend",
            summary="Backend code.",
            files=[FileSummary(path="backend/app.py", summary="Entry point.")],
        )
    ]


async def _seed_repo(session) -> Repo:
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


@pytest.mark.asyncio
async def test_generate_findings_parses_valid_response():
    calls = []
    payload = json.dumps(
        {
            "findings": [
                {
                    "title": "SQL injection in query builder",
                    "description": "User input concatenated directly into SQL.",
                    "category": "security",
                    "severity": "blocker",
                    "confidence": 0.9,
                    "files": [
                        {
                            "file_path": "backend/app.py",
                            "line_range": "10-12",
                            "rationale": "raw string concat",
                        }
                    ],
                }
            ]
        }
    )
    provider = _ScriptedProvider(responses=[payload])
    findings = await analyzer_mod._generate_findings(provider, _dirs(), calls)

    assert len(findings) == 1
    assert findings[0].title == "SQL injection in query builder"
    assert findings[0].severity == "blocker"
    assert findings[0].category == "security"
    assert findings[0].files[0].file_path == "backend/app.py"
    assert len(calls) == 1
    assert calls[0].step == "analysis_findings"
    assert calls[0].duration_ms is not None


@pytest.mark.asyncio
async def test_generate_findings_malformed_json_returns_empty():
    calls = []
    provider = _ScriptedProvider(responses=["not json at all"])
    findings = await analyzer_mod._generate_findings(provider, _dirs(), calls)

    assert findings == []
    # The call is still recorded for usage/cost tracking even though the
    # response was unparseable.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_findings_drops_unknown_file_citations():
    calls = []
    payload = json.dumps(
        {
            "findings": [
                {
                    "title": "x",
                    "description": "y",
                    "category": "bug",
                    "severity": "low",
                    "confidence": 0.5,
                    "files": [
                        {"file_path": "not/in/summaries.py", "line_range": "1", "rationale": "z"}
                    ],
                }
            ]
        }
    )
    provider = _ScriptedProvider(responses=[payload])
    findings = await analyzer_mod._generate_findings(provider, _dirs(), calls)

    assert len(findings) == 1
    assert findings[0].files == []


@pytest.mark.asyncio
async def test_generate_findings_clamps_unknown_severity_and_category():
    calls = []
    payload = json.dumps(
        {
            "findings": [
                {
                    "title": "x",
                    "description": "y",
                    "category": "not-a-real-category",
                    "severity": "catastrophic",
                    "confidence": 5,
                    "files": [],
                }
            ]
        }
    )
    provider = _ScriptedProvider(responses=[payload])
    findings = await analyzer_mod._generate_findings(provider, _dirs(), calls)

    assert findings[0].severity == "medium"
    assert findings[0].category == "maintainability"
    assert findings[0].confidence == 1.0  # clamped into [0, 1]


@pytest.mark.asyncio
async def test_write_finding_cards_idempotent(session):
    repo = await _seed_repo(session)
    finding = Finding(
        title="Race condition in cache invalidation",
        description="Two writers can invalidate concurrently.",
        category="reliability",
        severity="high",
        confidence=0.8,
        files=[
            FindingFile(file_path="backend/app.py", line_range="1-5", rationale="shared state")
        ],
    )

    cards = await write_finding_cards(session, repo=repo, branch="main", findings=[finding])
    await session.commit()

    assert len(cards) == 1
    card = cards[0]
    assert card.source == "analysis"
    assert card.issue_number is None
    assert card.classification == "bug"
    assert card.severity == "high"
    assert card.finding_category == "reliability"
    assert card.finding_key == finding_key(repo.id, "main", finding)

    # Re-running analysis with an unchanged finding must not duplicate.
    cards_again = await write_finding_cards(session, repo=repo, branch="main", findings=[finding])
    await session.commit()
    assert cards_again == []

    all_cards = (
        (await session.execute(select(TriageCard).where(TriageCard.repo_id == repo.id)))
        .scalars()
        .all()
    )
    assert len(all_cards) == 1


@pytest.mark.asyncio
async def test_write_finding_cards_empty_list_is_noop(session):
    repo = await _seed_repo(session)
    cards = await write_finding_cards(session, repo=repo, branch="main", findings=[])
    assert cards == []
