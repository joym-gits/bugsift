"""OpenAI GPT-4-class provider."""

from __future__ import annotations

import httpx

from bugsift.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    Usage,
)
from bugsift.llm.pricing import compute_cost

API_BASE = "https://api.openai.com"
DEFAULT_COMPLETION_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = DEFAULT_COMPLETION_MODEL,
        default_embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self._api_key = api_key
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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=60.0,
            )
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(self.name, response.status_code, "no choices returned")
        content = (choices[0].get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        used_model = data.get("model", body["model"])
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        return LLMResponse(
            content=content,
            model=used_model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=compute_cost(self.name, used_model, prompt_tokens, completion_tokens),
            ),
        )

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        body = {"model": model or self._default_embedding_model, "input": text}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=60.0,
            )
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        data = response.json()
        embeddings = data.get("data") or []
        if not embeddings:
            raise LLMProviderError(self.name, response.status_code, "no embedding returned")
        return [float(x) for x in embeddings[0].get("embedding", [])]
