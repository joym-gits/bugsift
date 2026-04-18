"""Optional live-provider integration tests.

Each test is skipped unless the corresponding ``*_API_KEY`` env var is set, so
the default ``pytest`` run in CI never makes a real network call. Run locally
with the env var set to prove a provider actually works end-to-end.
"""

from __future__ import annotations

import os

import pytest

from bugsift.llm.anthropic import AnthropicProvider
from bugsift.llm.base import ChatMessage
from bugsift.llm.google import GoogleProvider
from bugsift.llm.ollama import OllamaProvider
from bugsift.llm.openai import OpenAIProvider


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
async def test_anthropic_live_complete() -> None:
    provider = AnthropicProvider(os.environ["ANTHROPIC_API_KEY"])
    r = await provider.complete(
        [ChatMessage(role="user", content="Reply with exactly: ok")],
        max_tokens=16,
        temperature=0.0,
    )
    assert "ok" in r.content.lower()
    assert r.usage.prompt_tokens > 0


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_openai_live_complete_and_embed() -> None:
    provider = OpenAIProvider(os.environ["OPENAI_API_KEY"])
    r = await provider.complete(
        [ChatMessage(role="user", content="Reply with exactly: ok")],
        max_tokens=16,
        temperature=0.0,
    )
    assert "ok" in r.content.lower()
    vec = await provider.embed("hello")
    assert len(vec) == 1536


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set")
async def test_google_live_complete() -> None:
    provider = GoogleProvider(os.environ["GOOGLE_API_KEY"])
    r = await provider.complete(
        [ChatMessage(role="user", content="Reply with exactly: ok")],
        max_tokens=16,
        temperature=0.0,
    )
    assert "ok" in r.content.lower()


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OLLAMA_BASE_URL"), reason="OLLAMA_BASE_URL not set")
async def test_ollama_live_complete() -> None:
    provider = OllamaProvider(os.environ["OLLAMA_BASE_URL"])
    r = await provider.complete(
        [ChatMessage(role="user", content="Reply with exactly: ok")],
        max_tokens=16,
        temperature=0.0,
    )
    assert r.content.strip()
