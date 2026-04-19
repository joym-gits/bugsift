"""Built-in local embedder — no API key required.

Wraps ``fastembed`` (ONNX + tokenizer, pure Python, CPU-only) behind the
:class:`LLMProvider` interface so the retrieval + dedup steps can run
before a user has configured any hosted embedding provider. Only
``embed`` is implemented; ``complete`` raises — the orchestrator never
routes generation through this provider.

Model defaults to ``BAAI/bge-small-en-v1.5`` (384-dim, ~130 MB cached on
first use). Cached to disk inside the worker container so subsequent
boots are instant.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from bugsift.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}


def _get_model(model_name: str) -> Any:
    """Lazily instantiate + cache the TextEmbedding. First call may take
    a few seconds (downloads the ONNX weights); subsequent calls are
    cached per-process."""
    with _model_lock:
        cached = _model_cache.get(model_name)
        if cached is not None:
            return cached
        from fastembed import TextEmbedding

        logger.info("local embedder: loading %s (first use downloads weights)", model_name)
        model = TextEmbedding(model_name=model_name)
        _model_cache[model_name] = model
        return model


class LocalEmbeddingProvider(LLMProvider):
    """Key-free embedding provider backed by ``fastembed``.

    This isn't selectable in the UI as an LLM for classification — it
    only implements :meth:`embed`. The retrieval layer is the only
    caller.
    """

    name = "local"

    def __init__(self, _secret: str = "") -> None:
        # ``_secret`` is ignored — accepted only so this slots into
        # :func:`build_provider` without a special case.
        self._model_name = DEFAULT_EMBEDDING_MODEL

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        raise LLMProviderError(
            self.name,
            None,
            "local provider only supports embeddings; configure a hosted provider "
            "(anthropic/openai/google/ollama) for classification",
        )

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        model_name = model or self._model_name
        # fastembed is sync + CPU-bound → thread pool keeps the event loop happy.
        vector = await asyncio.to_thread(self._embed_sync, model_name, text)
        return vector

    @staticmethod
    def _embed_sync(model_name: str, text: str) -> list[float]:
        model = _get_model(model_name)
        # TextEmbedding.embed yields numpy arrays; grab the first (only) row.
        for row in model.embed([text]):
            return [float(v) for v in row.tolist()]
        raise LLMProviderError("local", None, "fastembed returned no vectors")
