from __future__ import annotations

import pytest

from bugsift.db.models import Installation, Repo, User, UserApiKey
from bugsift.retrieval.embedding import (
    EmbeddingUnavailable,
    get_embedder_for_repo,
)
from bugsift.security import crypto


async def _seed(session, *, providers: list[str], pinned: str | None = None, pinned_dim: int | None = None):
    user = User(github_id=1, github_login="m", email=None)
    session.add(user)
    await session.flush()
    for p in providers:
        session.add(
            UserApiKey(
                user_id=user.id,
                provider=p,
                encrypted_key=crypto.encrypt(f"key-for-{p}"),
                masked_hint=f"{p}-****",
            )
        )
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="m/r",
        default_branch="main",
        indexing_status="pending",
        embedding_model=pinned,
        embedding_dim=pinned_dim,
    )
    session.add(repo)
    await session.commit()
    return user, repo


async def test_prefers_openai_when_available(session) -> None:
    user, repo = await _seed(session, providers=["ollama", "openai"])
    provider, choice = await get_embedder_for_repo(session, repo, user.id)
    assert choice.provider_name == "openai"
    assert choice.dim == 1536


async def test_falls_back_to_ollama(session) -> None:
    user, repo = await _seed(session, providers=["ollama"])
    _, choice = await get_embedder_for_repo(session, repo, user.id)
    assert choice.provider_name == "ollama"
    assert choice.dim == 768


async def test_anthropic_only_raises(session) -> None:
    user, repo = await _seed(session, providers=["anthropic"])
    with pytest.raises(EmbeddingUnavailable):
        await get_embedder_for_repo(session, repo, user.id)


async def test_pinned_repo_respects_choice(session) -> None:
    user, repo = await _seed(
        session,
        providers=["ollama", "openai"],
        pinned="ollama:nomic-embed-text",
        pinned_dim=768,
    )
    _, choice = await get_embedder_for_repo(session, repo, user.id)
    assert choice.provider_name == "ollama"
    assert choice.dim == 768


async def test_pinned_repo_raises_when_key_removed(session) -> None:
    user, repo = await _seed(
        session,
        providers=["anthropic"],
        pinned="openai:text-embedding-3-small",
        pinned_dim=1536,
    )
    with pytest.raises(EmbeddingUnavailable):
        await get_embedder_for_repo(session, repo, user.id)
