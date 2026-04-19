"""Factory for picking the right :class:`LLMProvider` for a user.

Decrypts the user's stored API key (or Ollama base URL) and returns a live
provider instance. Raises :class:`KeyError` when the user has no stored key
for the requested provider — callers can surface a 400.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import User, UserApiKey
from bugsift.llm.anthropic import AnthropicProvider
from bugsift.llm.base import LLMProvider
from bugsift.llm.google import GoogleProvider
from bugsift.llm.local_embed import LocalEmbeddingProvider
from bugsift.llm.ollama import OllamaProvider
from bugsift.llm.openai import OpenAIProvider
from bugsift.security import crypto


async def get_provider_for_user(
    session: AsyncSession, user: User, provider_name: str
) -> LLMProvider:
    row = (
        await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user.id, UserApiKey.provider == provider_name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError(f"no {provider_name} key stored for user {user.id}")
    secret = crypto.decrypt(row.encrypted_key)
    return build_provider(provider_name, secret)


def build_provider(provider_name: str, secret: str) -> LLMProvider:
    if provider_name == "anthropic":
        return AnthropicProvider(secret)
    if provider_name == "openai":
        return OpenAIProvider(secret)
    if provider_name == "google":
        return GoogleProvider(secret)
    if provider_name == "ollama":
        return OllamaProvider(secret)
    if provider_name == "local":
        # No secret — the local embedder is built into the worker image.
        return LocalEmbeddingProvider()
    raise ValueError(f"unknown provider {provider_name!r}")
