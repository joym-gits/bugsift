"""Cosine-distance search over per-repo embeddings.

The local development stack stores embeddings as JSON arrays so it can
run on a plain PostgreSQL install without the pgvector extension. We
rank candidates in Python, which is fast enough for the small candidate
sets this project uses during local triage.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import CodeChunk, IssueEmbedding


@dataclass(frozen=True)
class SimilarIssue:
    issue_number: int
    title: str
    body_excerpt: str
    similarity: float


@dataclass(frozen=True)
class SimilarChunk:
    file_path: str
    start_line: int
    end_line: int
    content: str
    similarity: float


def _column_for_dim(dim: int) -> str:
    if dim == 1536:
        return "embedding_1536"
    if dim == 768:
        return "embedding_768"
    if dim == 384:
        return "embedding_384"
    raise ValueError(f"unsupported embedding dim: {dim}")


async def nearest_issues(
    session: AsyncSession,
    *,
    repo_id: int,
    dim: int,
    query_vector: list[float],
    exclude_issue_number: int | None = None,
    limit: int = 5,
    min_similarity: float = 0.0,
) -> list[SimilarIssue]:
    col = _column_for_dim(dim)
    stmt = select(
        IssueEmbedding.issue_number,
        IssueEmbedding.title,
        IssueEmbedding.body_excerpt,
        getattr(IssueEmbedding, col),
    ).where(
        IssueEmbedding.repo_id == repo_id,
        getattr(IssueEmbedding, col).is_not(None),
    )
    if exclude_issue_number is not None:
        stmt = stmt.where(IssueEmbedding.issue_number != exclude_issue_number)
    rows = (await session.execute(stmt)).all()
    scored: list[SimilarIssue] = []
    for issue_number, title, body_excerpt, candidate_vector in rows:
        if candidate_vector is None:
            continue
        similarity = _cosine(query_vector, list(candidate_vector))
        if similarity >= min_similarity:
            scored.append(SimilarIssue(int(issue_number), title, body_excerpt, similarity))
    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:limit]


async def nearest_chunks(
    session: AsyncSession,
    *,
    repo_id: int,
    dim: int,
    query_vector: list[float],
    limit: int = 10,
    min_similarity: float = 0.0,
) -> list[SimilarChunk]:
    col = _column_for_dim(dim)
    stmt = select(
        CodeChunk.file_path,
        CodeChunk.start_line,
        CodeChunk.end_line,
        CodeChunk.content,
        getattr(CodeChunk, col),
    ).where(
        CodeChunk.repo_id == repo_id,
        getattr(CodeChunk, col).is_not(None),
    )
    rows = (await session.execute(stmt)).all()
    scored: list[SimilarChunk] = []
    for file_path, start_line, end_line, content, candidate_vector in rows:
        if candidate_vector is None:
            continue
        similarity = _cosine(query_vector, list(candidate_vector))
        if similarity >= min_similarity:
            scored.append(
                SimilarChunk(
                    file_path,
                    int(start_line),
                    int(end_line),
                    content,
                    similarity,
                )
            )
    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:limit]


async def chunks_containing_tokens(
    session: AsyncSession,
    *,
    repo_id: int,
    tokens: list[str],
    limit_per_token: int = 2,
) -> list[SimilarChunk]:
    """Find code chunks whose content contains any of ``tokens``.

    Used when the issue body mentions identifiers in backticks (e.g.
    ``renderList``, ``Charger.charge``) that the model should be able to
    see the definition of. Substring match via ILIKE — good enough for
    distinctive function/class names. Short or noisy tokens are filtered
    by the caller.
    """
    out: list[SimilarChunk] = []
    seen: set[tuple[str, int]] = set()
    for token in tokens:
        # Skip tokens that would cause runaway matches (too short or
        # purely punctuation/digits). The extractor already enforces
        # length>=3 but belt-and-braces.
        if len(token) < 3:
            continue
        sql = text(
            """
            SELECT file_path, start_line, end_line, content
            FROM code_chunks
            WHERE repo_id = :repo_id AND content ILIKE :needle
            ORDER BY length(content) ASC
            LIMIT :limit
            """
        )
        rows = (
            await session.execute(
                sql,
                {"repo_id": repo_id, "needle": f"%{token}%", "limit": limit_per_token},
            )
        ).all()
        for r in rows:
            key = (r.file_path, int(r.start_line))
            if key in seen:
                continue
            seen.add(key)
            # similarity=0.9: identifier match is strong but not as exact
            # as a named-file match (which is 1.0).
            out.append(
                SimilarChunk(
                    r.file_path, int(r.start_line), int(r.end_line), r.content, 0.9
                )
            )
    return out


async def chunks_for_paths(
    session: AsyncSession,
    *,
    repo_id: int,
    paths: list[str],
    limit_per_path: int = 3,
) -> list[SimilarChunk]:
    """Fetch code chunks for files the issue body already named (via a
    pasted stack trace, filename mention, etc.).

    ``paths`` entries are tried as both exact file_path matches and as
    basename suffix matches — users paste traces with repo-relative,
    absolute, or just basename paths depending on the runtime, and we
    want to catch all three. Returns at most ``limit_per_path`` chunks
    per distinct ``file_path`` actually found, ordered by start_line."""
    if not paths:
        return []

    # Build one SELECT per path so we can cap rows per file independently.
    # The list is tiny (bounded by ``extract_hints`` to ~20), so N queries
    # is fine; using a LATERAL JOIN would be marginally nicer but adds
    # complexity without a real performance win at this scale.
    out: list[SimilarChunk] = []
    seen: set[tuple[str, int]] = set()
    for path in paths:
        # Users paste traces with either a repo-relative path, an
        # absolute path (/app/foo/bar.py), or just the basename. Match
        # on exact or suffix so we catch all three forms.
        sql = text(
            """
            SELECT file_path, start_line, end_line, content
            FROM code_chunks
            WHERE repo_id = :repo_id
              AND (file_path = :exact OR file_path LIKE :suffix)
            ORDER BY start_line ASC
            LIMIT :limit
            """
        )
        rows = (
            await session.execute(
                sql,
                {
                    "repo_id": repo_id,
                    "exact": path,
                    "suffix": f"%/{path.lstrip('/')}",
                    "limit": limit_per_path,
                },
            )
        ).all()
        for r in rows:
            key = (r.file_path, int(r.start_line))
            if key in seen:
                continue
            seen.add(key)
            # similarity=1.0: this is a direct name match, which the
            # ranker should treat as a perfect candidate. The LLM still
            # decides relevance in the prompt, but we want these first.
            out.append(
                SimilarChunk(
                    r.file_path, int(r.start_line), int(r.end_line), r.content, 1.0
                )
            )
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


