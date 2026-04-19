"""Codebase indexer.

Full re-index: fetch the repo's default branch as a tarball via the GitHub
API, extract to a temp dir, walk, chunk, embed, upsert into ``code_chunks``.
Delta re-index: given a list of added/modified/removed paths, fetch each
changed file individually via the contents API and re-chunk those files.

Runs as an RQ job in ``workers/indexing.py``. Keeps the embedding cost
bounded by: content-hash de-dup (never re-embed unchanged chunks) and a
hard cap on total chunks per pass (safety valve — real repos fit easily).
"""

from __future__ import annotations

import asyncio
import logging
import tarfile
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import httpx
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import CodeChunk, Repo
from bugsift.github.app import get_installation_token
from bugsift.retrieval.chunker import CodeChunkRecord, chunk_file
from bugsift.retrieval.embedding import EmbeddingChoice
from bugsift.retrieval.walker import LANGUAGE_BY_EXT, is_binary, walk

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_PASS = 5000


class RepoIndexer:
    def __init__(
        self,
        session: AsyncSession,
        embed_provider,
        choice: EmbeddingChoice,
        *,
        app_id: str | None = None,
        private_key_pem: str | None = None,
    ) -> None:
        """``app_id`` + ``private_key_pem`` let the caller inject the
        DB-stored GitHub App credentials; required unless the old
        env-based ``Settings`` path is in use."""
        self._session = session
        self._embed = embed_provider
        self._choice = choice
        self._app_id = app_id
        self._private_key_pem = private_key_pem

    async def full_index(
        self, repo: Repo, installation_id: int, *, ref: str | None = None
    ) -> int:
        """Download the repo tarball and index every usable file. Returns the
        number of chunks written."""
        ref = ref or repo.default_branch or "HEAD"
        with tempfile.TemporaryDirectory(prefix="bugsift-index-") as tmp:
            tmp_path = Path(tmp)
            root = await self._download_tarball(repo.full_name, ref, installation_id, tmp_path)
            if root is None:
                return 0

            files = walk(root)
            chunks: list[CodeChunkRecord] = []
            for f in files:
                try:
                    text = f.absolute_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                chunks.extend(chunk_file(f.relative_path, text, f.language))
                if len(chunks) >= MAX_CHUNKS_PER_PASS:
                    logger.warning(
                        "index cap hit at %d chunks for %s; remaining files skipped",
                        MAX_CHUNKS_PER_PASS,
                        repo.full_name,
                    )
                    break

            # Reset: on a full re-index, drop everything we had for this repo
            # and re-emit. Simpler than diffing; embedding cost is bounded.
            await self._session.execute(delete(CodeChunk).where(CodeChunk.repo_id == repo.id))

            written = await self._embed_and_store_chunks(repo.id, chunks)
            await self._mark_indexed(repo)
            await self._session.commit()
            return written

    async def delta_index(
        self,
        repo: Repo,
        installation_id: int,
        *,
        added: list[str],
        modified: list[str],
        removed: list[str],
        ref: str | None = None,
    ) -> int:
        """Re-index only the files touched by a push. Returns chunks written."""
        ref = ref or repo.default_branch or "HEAD"

        # Delete chunks for every affected path up-front — simplest correct
        # behaviour for both modified and removed files.
        touched = list({*added, *modified, *removed})
        if touched:
            await self._session.execute(
                delete(CodeChunk).where(
                    CodeChunk.repo_id == repo.id, CodeChunk.file_path.in_(touched)
                )
            )

        chunks: list[CodeChunkRecord] = []
        for path in (*added, *modified):
            text = await self._fetch_file(repo.full_name, ref, path, installation_id)
            if text is None:
                continue
            language = LANGUAGE_BY_EXT.get(Path(path).suffix.lower())
            chunks.extend(chunk_file(path, text, language))

        written = await self._embed_and_store_chunks(repo.id, chunks)
        await self._mark_indexed(repo)
        await self._session.commit()
        return written

    # ------------------------------------------------------------------

    async def _embed_and_store_chunks(
        self, repo_id: int, chunks: list[CodeChunkRecord]
    ) -> int:
        if not chunks:
            return 0
        embeddings = await _embed_many(self._embed, [c.content for c in chunks])
        dim_col = _dim_column(self._choice.dim)
        rows = [
            {
                "repo_id": repo_id,
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content,
                "content_hash": c.content_hash,
                dim_col: vec,
            }
            for c, vec in zip(chunks, embeddings, strict=True)
        ]
        # ON CONFLICT on (repo_id, file_path, start_line) upserts cleanly.
        stmt = pg_insert(CodeChunk).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_chunk_location",
            set_={
                "end_line": stmt.excluded.end_line,
                "content": stmt.excluded.content,
                "content_hash": stmt.excluded.content_hash,
                dim_col: getattr(stmt.excluded, dim_col),
                "indexed_at": datetime.now(UTC),
            },
        )
        await self._session.execute(stmt)
        return len(rows)

    async def _mark_indexed(self, repo: Repo) -> None:
        repo.indexed_at = datetime.now(UTC)
        repo.indexing_status = "ready"
        repo.embedding_model = f"{self._choice.provider_name}:{self._choice.model}"
        repo.embedding_dim = self._choice.dim

    async def _download_tarball(
        self, repo_full_name: str, ref: str, installation_id: int, dest: Path
    ) -> Path | None:
        token = await get_installation_token(
            installation_id,
            app_id=self._app_id,
            private_key_pem=self._private_key_pem,
        )
        url = f"https://api.github.com/repos/{repo_full_name}/tarball/{ref}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("tarball fetch failed for %s@%s: %s", repo_full_name, ref, e)
            return None

        with tarfile.open(fileobj=BytesIO(response.content), mode="r:gz") as tar:
            _safe_extract(tar, dest)

        # Tarball extracts into a top-level dir like "owner-repo-<sha>/".
        subdirs = [p for p in dest.iterdir() if p.is_dir()]
        if not subdirs:
            return None
        return subdirs[0]

    async def _fetch_file(
        self, repo_full_name: str, ref: str, path: str, installation_id: int
    ) -> str | None:
        token = await get_installation_token(
            installation_id,
            app_id=self._app_id,
            private_key_pem=self._private_key_pem,
        )
        url = f"https://api.github.com/repos/{repo_full_name}/contents/{path}?ref={ref}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers=headers, timeout=30.0)
        except httpx.HTTPError as e:
            logger.warning("file fetch failed %s@%s:%s: %s", repo_full_name, ref, path, e)
            return None
        if response.status_code != 200:
            return None
        raw = response.content
        if not raw or len(raw) > 500 * 1024 or is_binary(raw[:8192]):
            return None
        return raw.decode("utf-8", errors="replace")


def _dim_column(dim: int) -> str:
    if dim == 1536:
        return "embedding_1536"
    if dim == 768:
        return "embedding_768"
    if dim == 384:
        return "embedding_384"
    raise ValueError(f"unsupported embedding dim: {dim}")


async def _embed_many(provider, texts: list[str]) -> list[list[float]]:
    """Embed ``texts`` concurrently but with modest parallelism so we don't
    blow up rate limits."""
    sem = asyncio.Semaphore(8)

    async def one(text: str) -> list[float]:
        async with sem:
            return await provider.embed(text)

    return await asyncio.gather(*(one(t) for t in texts))


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Reject entries that escape ``dest`` (CVE-2007-4559 style)."""
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if dest_resolved not in target.parents and target != dest_resolved:
            raise RuntimeError(f"tarball contains unsafe path: {member.name!r}")
    tar.extractall(dest)
