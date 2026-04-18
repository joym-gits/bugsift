"""LLMProvider interface.

Every prompt in bugsift is routed through :class:`LLMProvider`. The four
concrete implementations (Anthropic, OpenAI, Google, Ollama) live alongside
this file. No agent framework; no implicit tool routing; no autonomous
planning. The orchestrator calls ``complete`` deterministically and reads the
response. Embeddings are exposed through ``embed`` for phase 6 onwards.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: Usage


class LLMProviderError(RuntimeError):
    """Surfaced when a provider call fails. Keeps the status code and body snippet."""

    def __init__(self, provider: str, status_code: int | None, detail: str):
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{provider}: {detail}")


class LLMProvider(ABC):
    #: Lowercase slug matching ``user_api_keys.provider``.
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """Generate a completion from a chat history. ``temperature`` is a float in ``[0, 1]``."""

    @abstractmethod
    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        """Return an embedding vector. Providers without a native embeddings API
        raise :class:`NotImplementedError` — callers should fall back to another
        configured provider."""
