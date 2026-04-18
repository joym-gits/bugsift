"""Anthropic Claude provider."""

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

API_BASE = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, *, default_model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._default_model = default_model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        system_parts = [m.content for m in messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        body: dict[str, object] = {
            "model": model or self._default_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
                timeout=60.0,
            )
        if response.status_code != 200:
            raise LLMProviderError(self.name, response.status_code, response.text[:500])
        data = response.json()
        text = "".join(
            part.get("text", "") for part in data.get("content", []) if part.get("type") == "text"
        )
        usage = data.get("usage", {}) or {}
        used_model = data.get("model", body["model"])
        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
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
        raise NotImplementedError(
            "Anthropic has no native embeddings API. Configure an OpenAI, Google, "
            "or Ollama key for embeddings (used from phase 6 onwards)."
        )
