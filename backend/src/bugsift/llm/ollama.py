"""Ollama provider (local / self-hosted).

Ollama exposes a plain HTTP API on ``http://localhost:11434`` by default.
Users who select ``ollama`` in the dashboard paste their Ollama base URL into
the key field (the UI explains this) — there's no API key in the usual sense.
"""

from __future__ import annotations

import httpx

from bugsift.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    Usage,
)

DEFAULT_COMPLETION_MODEL = "llama3.2"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        default_model: str = DEFAULT_COMPLETION_MODEL,
        default_embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._default_embedding_model = default_embedding_model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        body = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/chat", json=body, timeout=120.0
            )
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        data = response.json()
        content = (data.get("message") or {}).get("content", "")
        used_model = data.get("model", body["model"])
        prompt_tokens = int(data.get("prompt_eval_count", 0))
        completion_tokens = int(data.get("eval_count", 0))
        return LLMResponse(
            content=content,
            model=used_model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=0.0,
            ),
        )

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        body = {"model": model or self._default_embedding_model, "prompt": text}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/embeddings", json=body, timeout=60.0
            )
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        values = response.json().get("embedding") or []
        return [float(x) for x in values]
