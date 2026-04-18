from __future__ import annotations

import pytest
import respx
from httpx import Response

from bugsift.llm.anthropic import API_BASE as ANTHROPIC_BASE
from bugsift.llm.anthropic import AnthropicProvider
from bugsift.llm.base import ChatMessage, LLMProviderError
from bugsift.llm.google import API_BASE as GOOGLE_BASE
from bugsift.llm.google import GoogleProvider
from bugsift.llm.ollama import OllamaProvider
from bugsift.llm.openai import API_BASE as OPENAI_BASE
from bugsift.llm.openai import OpenAIProvider

# -------------------- Anthropic --------------------


@respx.mock
async def test_anthropic_complete_parses_response_and_cost() -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=Response(
            200,
            json={
                "id": "msg_1",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            },
        )
    )
    provider = AnthropicProvider("sk-ant-test")
    r = await provider.complete([ChatMessage(role="user", content="hi")])
    assert r.content == "ok"
    assert r.model == "claude-sonnet-4-6"
    assert r.usage.prompt_tokens == 12
    assert r.usage.completion_tokens == 3
    assert r.usage.cost_usd > 0  # pricing table hit


@respx.mock
async def test_anthropic_complete_separates_system_message() -> None:
    route = respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=Response(200, json={"model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "yo"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    )
    provider = AnthropicProvider("sk-ant-test")
    await provider.complete(
        [ChatMessage(role="system", content="be terse"), ChatMessage(role="user", content="hi")]
    )
    sent = route.calls[0].request.read()
    import json as _json

    body = _json.loads(sent)
    assert body["system"] == "be terse"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


@respx.mock
async def test_anthropic_raises_on_error_status() -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=Response(401, text='{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}')
    )
    provider = AnthropicProvider("bad")
    with pytest.raises(LLMProviderError) as exc:
        await provider.complete([ChatMessage(role="user", content="hi")])
    assert exc.value.status_code == 401
    assert "invalid x-api-key" in exc.value.detail


async def test_anthropic_embed_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await AnthropicProvider("sk-ant-test").embed("hello")


# -------------------- OpenAI --------------------


@respx.mock
async def test_openai_complete_parses_response() -> None:
    respx.post(f"{OPENAI_BASE}/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )
    )
    provider = OpenAIProvider("sk-openai-test")
    r = await provider.complete([ChatMessage(role="user", content="hi")])
    assert r.content == "ok"
    assert r.model == "gpt-4o-mini"
    assert r.usage.prompt_tokens == 10
    assert r.usage.completion_tokens == 2


@respx.mock
async def test_openai_embed_returns_vector() -> None:
    respx.post(f"{OPENAI_BASE}/v1/embeddings").mock(
        return_value=Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}], "model": "text-embedding-3-small"})
    )
    provider = OpenAIProvider("sk-openai-test")
    vec = await provider.embed("hello world")
    assert vec == [0.1, 0.2, 0.3]


# -------------------- Google --------------------


@respx.mock
async def test_google_complete_parses_gemini_response() -> None:
    respx.post(f"{GOOGLE_BASE}/v1beta/models/gemini-1.5-flash:generateContent").mock(
        return_value=Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 1},
            },
        )
    )
    provider = GoogleProvider("goog-test")
    r = await provider.complete([ChatMessage(role="user", content="hi")])
    assert r.content == "ok"
    assert r.model == "gemini-1.5-flash"
    assert r.usage.prompt_tokens == 8


@respx.mock
async def test_google_embed_returns_vector() -> None:
    respx.post(f"{GOOGLE_BASE}/v1beta/models/text-embedding-004:embedContent").mock(
        return_value=Response(200, json={"embedding": {"values": [0.4, 0.5]}})
    )
    provider = GoogleProvider("goog-test")
    vec = await provider.embed("hi")
    assert vec == [0.4, 0.5]


# -------------------- Ollama --------------------


@respx.mock
async def test_ollama_complete_returns_zero_cost() -> None:
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(
            200,
            json={
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "ok"},
                "prompt_eval_count": 5,
                "eval_count": 1,
                "done": True,
            },
        )
    )
    provider = OllamaProvider("http://localhost:11434")
    r = await provider.complete([ChatMessage(role="user", content="hi")])
    assert r.content == "ok"
    assert r.usage.cost_usd == 0.0


@respx.mock
async def test_ollama_embed_returns_vector() -> None:
    respx.post("http://localhost:11434/api/embeddings").mock(
        return_value=Response(200, json={"embedding": [0.01, 0.02]})
    )
    provider = OllamaProvider("http://localhost:11434")
    vec = await provider.embed("hi")
    assert vec == [0.01, 0.02]
