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


def _pg_vector_literal(values: list[float]) -> str:
    """Render a Python list as pgvector's textual format: ``[0.1, 0.2, ...]``."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


