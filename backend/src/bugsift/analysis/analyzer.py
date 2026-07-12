"""Hierarchical repo analyser.

Three passes (cheap → synthesising):

1. **File summaries** — for every file we have indexed chunks for,
   stitch the chunks back into text and ask the LLM for a 1–2 sentence
   role summary. Bounded at one LLM call per file; files missing from
   :class:`CodeChunk` are skipped (they were binary, too big, or
   unsupported language at index time).
2. **Directory summaries** — group files by parent directory, ask the
   LLM to describe the directory as a whole using the file summaries
   as context. One call per directory.
3. **Top-level synthesis** — render the directory summaries and any
   user-supplied overrides into a single prompt, ask for the structured
   JSON object the dashboard will render (components + entry points +
   flows + Mermaid overview).

All calls go through the user's configured classifier LLM (Anthropic
by default). Every step is failure-tolerant: an individual call that
returns junk is dropped with a warning, never aborting the whole pass.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.agent.prompts import render
from bugsift.agent.state import LLMCallRecord
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.db.models import CodeChunk
from bugsift.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

MAX_FILE_CHARS = 6000  # clip enormous files so the prompt stays cheap
MAX_FILES = 400  # hard cap per analysis — huge monorepos get truncated
MAX_FINDINGS = 15  # cap per analysis run — keeps the findings pass bounded
_SEVERITIES = {"blocker", "high", "medium", "low"}
_CATEGORIES = {"bug", "security", "performance", "maintainability", "reliability"}


@dataclass(frozen=True)
class FileSummary:
    path: str
    summary: str


@dataclass(frozen=True)
class DirectorySummary:
    path: str
    summary: str
    files: list[FileSummary]


@dataclass(frozen=True)
class FindingFile:
    file_path: str
    line_range: str
    rationale: str


@dataclass(frozen=True)
class Finding:
    title: str
    description: str
    category: str  # bug|security|performance|maintainability|reliability
    severity: str  # blocker|high|medium|low
    confidence: float
    files: list[FindingFile]


@dataclass
class AnalysisResult:
    structured: dict
    mermaid_overview: str
    # Per-file + per-dir intermediates so the dashboard can show the full
    # breakdown if the operator wants to drill in.
    files: list[FileSummary]
    directories: list[DirectorySummary]
    findings: list[Finding] = field(default_factory=list)
    # Every LLM call made during this run, for cost/duration tracking.
    llm_calls: list[LLMCallRecord] = field(default_factory=list)


async def analyze_repo(
    session: AsyncSession,
    *,
    repo_id: int,
    provider: LLMProvider,
    overrides: list[str] | None = None,
    max_findings: int = MAX_FINDINGS,
) -> AnalysisResult:
    """Run the three-pass analyser for ``repo_id`` and return the final
    structured result. Assumes the repo has been indexed already — the
    caller is responsible for guarding on that."""
    file_chunks = await _load_file_chunks(session, repo_id)
    if not file_chunks:
        raise ValueError(
            f"repo_id={repo_id} has no indexed code_chunks; run indexing first"
        )

    logger.info(
        "analyze_repo: repo_id=%s files=%d", repo_id, len(file_chunks)
    )

    calls: list[LLMCallRecord] = []

    files: list[FileSummary] = []
    for path, text, language in file_chunks:
        try:
            summary = await _summarise_file(provider, path, text, language, calls)
        except Exception:
            logger.warning("analyze_repo: file summary failed for %s", path, exc_info=True)
            continue
        if summary:
            files.append(FileSummary(path=path, summary=summary))

    directories: list[DirectorySummary] = []
    for dir_path, grouped in _group_by_directory(files).items():
        try:
            summary = await _summarise_directory(provider, dir_path, grouped, calls)
        except Exception:
            logger.warning(
                "analyze_repo: dir summary failed for %s", dir_path, exc_info=True
            )
            summary = _fallback_dir_summary(grouped)
        directories.append(
            DirectorySummary(path=dir_path, summary=summary, files=grouped)
        )

    structured = await _synthesise(provider, directories, overrides or [], calls)
    mermaid_overview = str(structured.get("mermaid_overview") or "").strip()

    try:
        findings = await _generate_findings(
            provider, directories, calls, max_findings=max_findings
        )
    except Exception:
        logger.warning("analyze_repo: findings pass failed for repo_id=%s", repo_id, exc_info=True)
        findings = []

    return AnalysisResult(
        structured=structured,
        mermaid_overview=mermaid_overview,
        files=files,
        directories=directories,
        findings=findings,
        llm_calls=calls,
    )


async def _load_file_chunks(
    session: AsyncSession, repo_id: int
) -> list[tuple[str, str, str | None]]:
    """Return ``(file_path, joined_content, language)`` per indexed file,
    ordered by file_path + start_line. Files whose concatenated content
    exceeds :data:`MAX_FILE_CHARS` get clipped at the start — the tail
    (which usually has the public surface) is what summaries key on."""
    rows = (
        await session.execute(
            select(CodeChunk.file_path, CodeChunk.start_line, CodeChunk.content)
            .where(CodeChunk.repo_id == repo_id)
            .order_by(CodeChunk.file_path.asc(), CodeChunk.start_line.asc())
        )
    ).all()
    by_file: dict[str, list[str]] = {}
    for path, _, content in rows:
        by_file.setdefault(path, []).append(content)
    out: list[tuple[str, str, str | None]] = []
    for path, pieces in list(by_file.items())[:MAX_FILES]:
        text = "\n".join(pieces)
        if len(text) > MAX_FILE_CHARS:
            text = text[-MAX_FILE_CHARS:]
        out.append((path, text, _guess_language(path)))
    return out


def _record_call(
    calls: list[LLMCallRecord], step: str, response, started_at: float
) -> None:
    calls.append(
        LLMCallRecord(
            step=step,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost_usd=response.usage.cost_usd,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
    )


async def _summarise_file(
    provider: LLMProvider,
    path: str,
    content: str,
    language: str | None,
    calls: list[LLMCallRecord],
) -> str:
    prompt = render(
        "analyze_file.j2",
        file_path=path,
        content=content,
        language=language,
    )
    t0 = time.monotonic()
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=220,
        temperature=0.1,
    )
    _record_call(calls, "analysis_file_summary", response, t0)
    return response.content.strip()


async def _summarise_directory(
    provider: LLMProvider,
    dir_path: str,
    files: list[FileSummary],
    calls: list[LLMCallRecord],
) -> str:
    prompt = render(
        "analyze_directory.j2",
        directory_path=dir_path,
        files=[{"path": f.path, "summary": f.summary} for f in files],
    )
    t0 = time.monotonic()
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=300,
        temperature=0.1,
    )
    _record_call(calls, "analysis_dir_summary", response, t0)
    return response.content.strip()


async def _synthesise(
    provider: LLMProvider,
    directories: list[DirectorySummary],
    overrides: list[str],
    calls: list[LLMCallRecord],
) -> dict:
    prompt = render(
        "analyze.j2",
        directories=[
            {
                "path": d.path,
                "summary": d.summary,
                "files": [{"path": f.path, "summary": f.summary} for f in d.files],
            }
            for d in directories
        ],
        overrides=overrides,
    )
    t0 = time.monotonic()
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=2200,
        temperature=0.1,
    )
    _record_call(calls, "analysis_synthesis", response, t0)
    try:
        return parse_json_object(response.content)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(
            "analyze_repo: synthesis returned unparseable JSON; falling back. err=%s",
            e,
        )
        return _fallback_synthesis(directories)


async def _generate_findings(
    provider: LLMProvider,
    directories: list[DirectorySummary],
    calls: list[LLMCallRecord],
    *,
    max_findings: int = MAX_FINDINGS,
) -> list[Finding]:
    """Evaluative pass, separate from :func:`_synthesise` on purpose —
    that prompt is descriptive/architecture-framed and tightly token
    budgeted; bug-hunting needs a different framing and its own budget,
    and a parse failure here shouldn't blank out the architecture map."""
    prompt = render(
        "findings.j2",
        directories=[
            {
                "path": d.path,
                "summary": d.summary,
                "files": [{"path": f.path, "summary": f.summary} for f in d.files],
            }
            for d in directories
        ],
        max_findings=max_findings,
    )
    t0 = time.monotonic()
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=2200,
        temperature=0.1,
    )
    _record_call(calls, "analysis_findings", response, t0)
    try:
        parsed = parse_json_object(response.content)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(
            "analyze_repo: findings returned unparseable JSON; skipping. err=%s", e
        )
        return []
    raw = parsed.get("findings")
    if not isinstance(raw, list):
        return []

    known_paths = {f.path for d in directories for f in d.files}
    out: list[Finding] = []
    for item in raw[:max_findings]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        files = [
            FindingFile(
                file_path=str(f["file_path"]),
                line_range=str(f.get("line_range") or ""),
                rationale=str(f.get("rationale") or ""),
            )
            for f in (item.get("files") or [])
            if isinstance(f, dict) and f.get("file_path") in known_paths
        ]
        try:
            confidence = float(item.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        out.append(
            Finding(
                title=title[:200],
                description=str(item.get("description") or "").strip(),
                category=_clamp_category(item.get("category")),
                severity=_clamp_severity(item.get("severity")),
                confidence=min(max(confidence, 0.0), 1.0),
                files=files,
            )
        )
    return out


def _clamp_severity(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in _SEVERITIES else "medium"


def _clamp_category(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in _CATEGORIES else "maintainability"


def _fallback_synthesis(directories: list[DirectorySummary]) -> dict:
    """If the LLM mangled the JSON on us, still give the dashboard
    something to render. Use the directory summaries as components and
    emit a trivial mermaid block."""
    components = [
        {
            "name": (d.path.split("/")[-1] or "root").title(),
            "path": d.path,
            "role": d.summary,
            "citations": [f.path for f in d.files[:3]],
        }
        for d in directories
    ]
    mermaid_lines = ["graph TD"]
    for i, c in enumerate(components):
        mermaid_lines.append(f"  N{i}[\"{c['name']}\"]")
    return {
        "summary": "Automated fallback: synthesis LLM response did not parse.",
        "components": components,
        "entry_points": [],
        "dependencies": [],
        "flows": [],
        "mermaid_overview": "\n".join(mermaid_lines),
    }


def _fallback_dir_summary(files: list[FileSummary]) -> str:
    return "Directory containing " + ", ".join(
        PurePosixPath(f.path).name for f in files[:5]
    ) + ("..." if len(files) > 5 else "")


def _group_by_directory(files: list[FileSummary]) -> dict[str, list[FileSummary]]:
    grouped: dict[str, list[FileSummary]] = {}
    for f in files:
        parent = str(PurePosixPath(f.path).parent)
        if parent == ".":
            parent = ""
        grouped.setdefault(parent, []).append(f)
    return dict(sorted(grouped.items()))


def _guess_language(path: str) -> str | None:
    ext = PurePosixPath(path).suffix.lower().lstrip(".")
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "go": "go",
        "java": "java",
        "rb": "ruby",
        "rs": "rust",
        "php": "php",
        "sh": "bash",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "md": "markdown",
    }.get(ext)
