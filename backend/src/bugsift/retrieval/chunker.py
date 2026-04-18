"""Windowed chunking for code files.

v1 uses a line-window sliding chunker with overlap. AST-aware chunking via
tree-sitter is spec'd in §7 and noted as a follow-up — good enough windowed
chunking produces usable embeddings for dedup and retrieval, and doesn't
pull in a native build dep. Upgrade to AST when golden-set retrieval numbers
demand it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

WINDOW_SIZE = 60  # target lines per chunk (§7 says 40-80)
OVERLAP = 10  # overlap between adjacent chunks


@dataclass(frozen=True)
class CodeChunkRecord:
    file_path: str
    language: str | None
    start_line: int  # 1-indexed, inclusive
    end_line: int  # 1-indexed, inclusive
    content: str
    content_hash: str


def chunk_file(file_path: str, text: str, language: str | None = None) -> list[CodeChunkRecord]:
    """Split ``text`` into overlapping line windows. Returns an empty list for
    empty files or files that are a single chunk smaller than ``WINDOW_SIZE``
    — the caller decides whether to store small files whole.
    """
    lines = text.splitlines()
    if not lines:
        return []

    total = len(lines)
    if total <= WINDOW_SIZE:
        return [_make_chunk(file_path, language, 1, total, "\n".join(lines))]

    out: list[CodeChunkRecord] = []
    step = WINDOW_SIZE - OVERLAP  # e.g. 50 when WINDOW=60 / OVERLAP=10
    start = 1
    while start <= total:
        end = min(start + WINDOW_SIZE - 1, total)
        slab = "\n".join(lines[start - 1 : end])
        out.append(_make_chunk(file_path, language, start, end, slab))
        if end >= total:
            break
        start += step
    return out


def _make_chunk(
    file_path: str, language: str | None, start: int, end: int, content: str
) -> CodeChunkRecord:
    h = hashlib.sha256(f"{file_path}\n{start}\n{end}\n{content}".encode()).hexdigest()
    return CodeChunkRecord(
        file_path=file_path,
        language=language,
        start_line=start,
        end_line=end,
        content=content,
        content_hash=h,
    )
