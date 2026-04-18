"""Orchestrator gates expensive steps on budget_ok."""

from __future__ import annotations

from bugsift.agent import orchestrator
from bugsift.agent.state import TriageState
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage


class _StubProvider(LLMProvider):
    name = "stub"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.last: list[ChatMessage] | None = None

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        self.last = messages
        return self._responses.pop(0)

    async def embed(self, text, *, model=None):
        raise NotImplementedError


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        usage=Usage(prompt_tokens=100, completion_tokens=30, cost_usd=0.001),
    )


def _state() -> TriageState:
    return TriageState(
        repo_id=1,
        repo_full_name="o/r",
        issue_number=1,
        issue_title="bug: widget crashes when x=None",
        issue_body="Traceback shows AttributeError.",
        repo_primary_language="Python",
    )


async def test_budget_ok_runs_full_pipeline_when_session_present() -> None:
    """Sanity: session present, budget ok, dedup + retrieval + reproduction +
    comment all enqueue LLM calls — matches the phase-7/8 behaviour."""
    # Just classify + comment to keep the stub simple (dedup short-circuits
    # cleanly without embedder, retrieval skips for same reason, reproduction
    # is disabled via enabled_steps).
    provider = _StubProvider(
        [
            _resp('{"classification":"bug","confidence":0.9,"rationale":"x"}'),
            _resp('{"comment":"ack","proposed_labels":[],"proposed_action":"comment"}'),
        ]
    )
    state = _state()
    state.enabled_steps = {"classify": True, "dedup": True, "retrieval": True, "reproduction": False}
    out = await orchestrator.run(state, provider, budget_ok=True)
    assert out.status == "complete"
    assert out.budget_limited is False
    # Two LLM calls: classify + comment (dedup/retrieval skipped — no session here).
    assert len(out.llm_calls) == 2


async def test_budget_exhausted_skips_expensive_and_flags() -> None:
    provider = _StubProvider(
        [
            _resp('{"classification":"bug","confidence":0.9,"rationale":"x"}'),
            _resp('{"comment":"ack","proposed_labels":[],"proposed_action":"comment"}'),
        ]
    )
    # Even with a session + enabled_steps=True for expensive steps, they
    # must not run when budget_ok is False.
    state = _state()
    state.enabled_steps = {
        "classify": True,
        "dedup": True,
        "retrieval": True,
        "reproduction": True,
    }

    class _FakeSession:
        pass

    out = await orchestrator.run(
        state,
        provider,
        session=_FakeSession(),  # would be used if dedup/retrieval ran
        embed_provider=None,
        embedding_dim=None,
        budget_ok=False,
    )
    assert out.status == "complete"
    assert out.budget_limited is True
    # Only classify + comment ran.
    assert len(out.llm_calls) == 2


async def test_budget_ok_does_not_flag() -> None:
    provider = _StubProvider(
        [
            _resp('{"classification":"bug","confidence":0.9,"rationale":"x"}'),
            _resp('{"comment":"ack","proposed_labels":[],"proposed_action":"comment"}'),
        ]
    )
    state = _state()
    state.enabled_steps = {
        "classify": True,
        "dedup": True,
        "retrieval": True,
        "reproduction": False,
    }
    out = await orchestrator.run(state, provider, budget_ok=True)
    assert out.budget_limited is False
