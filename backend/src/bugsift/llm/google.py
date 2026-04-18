"""Google Gemini provider."""

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

API_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_COMPLETION_MODEL = "gemini-1.5-flash"
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"


class GoogleProvider(LLMProvider):
    name = "google"

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
        system_parts = [m.content for m in messages if m.role == "system"]
        contents = [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != "system"
        ]
        body: dict[str, object] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        used_model = model or self._default_model
        url = f"{API_BASE}/v1beta/models/{used_model}:generateContent?key={self._api_key}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=body, timeout=60.0)
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMProviderError(self.name, response.status_code, "no candidates returned")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        return LLMResponse(
            content=text,
            model=used_model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=compute_cost(self.name, used_model, prompt_tokens, completion_tokens),
            ),
        )

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        used_model = model or self._default_embedding_model
        url = f"{API_BASE}/v1beta/models/{used_model}:embedContent?key={self._api_key}"
        body = {"content": {"parts": [{"text": text}]}}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=body, timeout=60.0)
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        values = ((response.json().get("embedding") or {}).get("values")) or []
        return [float(x) for x in values]
