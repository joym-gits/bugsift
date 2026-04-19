"""pgvector cosine-distance search over per-repo embeddings.

``<=>`` is pgvector's cosine-distance operator; we return ``similarity = 1 -
distance`` so a higher number is a better match, matching the brief's
language around thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
    vector_literal = _pg_vector_literal(query_vector)
    exclusion_sql = ""
    params = {"repo_id": repo_id, "limit": limit, "min_sim": min_similarity, "vec": vector_literal}
    if exclude_issue_number is not None:
        exclusion_sql = "AND issue_number <> :exclude_number"
        params["exclude_number"] = exclude_issue_number

    sql = text(
        f"""
        SELECT issue_number, title, body_excerpt,
               1 - ({col} <=> CAST(:vec AS vector)) AS similarity
        FROM issue_embeddings
        WHERE repo_id = :repo_id
          AND {col} IS NOT NULL
          {exclusion_sql}
        ORDER BY {col} <=> CAST(:vec AS vector)
        LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).all()
    return [
        SimilarIssue(r.issue_number, r.title, r.body_excerpt, float(r.similarity))
        for r in rows
        if float(r.similarity) >= min_similarity
    ]


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
    vector_literal = _pg_vector_literal(query_vector)
    sql = text(
        f"""
        SELECT file_path, start_line, end_line, content,
               1 - ({col} <=> CAST(:vec AS vector)) AS similarity
        FROM code_chunks
        WHERE repo_id = :repo_id
          AND {col} IS NOT NULL
        ORDER BY {col} <=> CAST(:vec AS vector)
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            sql, {"repo_id": repo_id, "limit": limit, "vec": vector_literal}
        )
    ).all()
    return [
        SimilarChunk(
            r.file_path, int(r.start_line), int(r.end_line), r.content, float(r.similarity)
        )
        for r in rows
        if float(r.similarity) >= min_similarity
    ]


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


def _pg_vector_literal(values: list[float]) -> str:
    """Render a Python list as pgvector's textual format: ``[0.1, 0.2, ...]``."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


