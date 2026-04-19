"""Pick an embedding-capable provider for a user, honouring per-repo dim.

Each repo stores its chosen embedding model + dimension on first index. All
future embeddings for that repo MUST match. If the user no longer has a key
for the chosen provider, we raise :class:`EmbeddingUnavailable` — the
orchestrator treats that as a skip.

Preference order when a repo has no recorded choice yet:
1. ``openai`` (text-embedding-3-small, 1536) — highest quality, minor cost
2. ``ollama`` (nomic-embed-text, 768) — free + local (Ollama host)
3. ``google`` (text-embedding-004, 768) — free tier
4. ``local`` (bge-small-en-v1.5, 384) — built-in fallback, no key needed

Anthropic has no embeddings API and is never selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.db.models import Repo, UserApiKey
from bugsift.llm.base import LLMProvider
from bugsift.llm.factory import build_provider
from bugsift.security import crypto

# provider -> (model, dim)
PROVIDER_DEFAULTS: dict[str, tuple[str, int]] = {
    "openai": ("text-embedding-3-small", 1536),
    "ollama": ("nomic-embed-text", 768),
    "google": ("text-embedding-004", 768),
    "local": ("BAAI/bge-small-en-v1.5", 384),
}

# Highest-quality first. ``local`` is the key-free fallback so a fresh
# install can run dedup + retrieval without the user configuring an
# embedding provider.
PREFERENCE_ORDER: tuple[str, ...] = ("openai", "ollama", "google", "local")


@dataclass(frozen=True)
class EmbeddingChoice:
    provider_name: str
    model: str
    dim: int


class EmbeddingUnavailable(RuntimeError):
    """Raised when no compatible embedding provider is available for the repo."""


async def get_embedder_for_repo(
    session: AsyncSession, repo: Repo, user_id: int
) -> tuple[LLMProvider, EmbeddingChoice]:
    """Return a ready provider + the chosen (model, dim).

    If the repo already has an ``embedding_model`` recorded, we require the
    matching provider. Otherwise we pick from :data:`PREFERENCE_ORDER` based
    on what keys the user has stored.
    """
    user_keys = await _user_key_map(session, user_id)

    if repo.embedding_model:
        # Locked in — find the key that produces this model.
        provider_name, model_name = repo.embedding_model.split(":", 1)
        if provider_name == "local":
            provider = build_provider("local", "")
            return provider, EmbeddingChoice("local", model_name, repo.embedding_dim or 0)
        if provider_name not in user_keys:
            raise EmbeddingUnavailable(
                f"repo pinned to {repo.embedding_model} but user has no {provider_name} key"
            )
        provider = build_provider(provider_name, user_keys[provider_name])
        return provider, EmbeddingChoice(provider_name, model_name, repo.embedding_dim or 0)

    for provider_name in PREFERENCE_ORDER:
        if provider_name == "local":
            model, dim = PROVIDER_DEFAULTS["local"]
            provider = build_provider("local", "")
            return provider, EmbeddingChoice("local", model, dim)
        if provider_name in user_keys:
            model, dim = PROVIDER_DEFAULTS[provider_name]
            provider = build_provider(provider_name, user_keys[provider_name])
            return provider, EmbeddingChoice(provider_name, model, dim)

    raise EmbeddingUnavailable(
        "no embedding provider available (unexpected — local should always be a fallback)"
    )


async def _user_key_map(session: AsyncSession, user_id: int) -> dict[str, str]:
    rows = (
        await session.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))
    ).scalars().all()
    out: dict[str, str] = {}
    for row in rows:
        if row.provider == "anthropic":
            continue  # no embeddings API
        try:
            out[row.provider] = crypto.decrypt(row.encrypted_key)
        except crypto.DecryptionFailed:
            continue
    return out


def model_slug(choice: EmbeddingChoice) -> str:
    """``provider:model`` string stored on ``repos.embedding_model``."""
    return f"{choice.provider_name}:{choice.model}"
