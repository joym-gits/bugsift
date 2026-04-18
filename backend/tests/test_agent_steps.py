from __future__ import annotations

import pytest

from bugsift.agent.state import TriageState
from bugsift.agent.steps import classify as classify_step
from bugsift.agent.steps import comment as comment_step
from bugsift.agent.steps import ingest
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage


class _StubProvider(LLMProvider):
    """LLMProvider returning canned responses in order."""

    name = "stub"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.last_messages: list[ChatMessage] | None = None

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        self.last_messages = messages
        return self._responses.pop(0)

    async def embed(self, text, *, model=None):
        raise NotImplementedError


def _resp(content: str, *, model: str = "claude-sonnet-4-6") -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        usage=Usage(prompt_tokens=100, completion_tokens=50, cost_usd=0.001),
    )


def _state(**overrides) -> TriageState:
    base = dict(
        repo_id=1,
        repo_full_name="octo/widget",
        repo_primary_language="Python",
        issue_number=42,
        issue_title="Widget crashes on null input",
        issue_body="When I pass None I get AttributeError.",
        tone="professional",
        label_map={"bug": "bug", "feature_request": "enhancement", "needs_info": "needs-info"},
    )
    base.update(overrides)
    return TriageState(**base)


# -------------------- JSON parse helper --------------------


def test_parse_json_object_plain() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_strips_fence() -> None:
    assert parse_json_object("```json\n{\"a\": 1}\n```") == {"a": 1}


def test_parse_json_object_rescues_prose() -> None:
    assert parse_json_object("Sure! Here you go: {\"a\": 1} end") == {"a": 1}


def test_parse_json_object_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        parse_json_object("not json at all")


# -------------------- Ingest --------------------


def test_ingest_builds_state_from_webhook_payload() -> None:
    payload = {
        "issue": {
            "number": 7,
            "title": "a thing",
            "body": "boom",
            "user": {"login": "alice"},
            "labels": [{"name": "triaged"}],
        },
        "repository": {"full_name": "o/r"},
    }
    s = ingest.from_webhook_payload(
        payload=payload,
        repo_id=1,
        repo_full_name="o/r",
        repo_primary_language="Go",
        repo_config={
            "tone": "terse",
            "label_map": {"bug": "bug"},
            "mode": "dry-run",
            "enabled_steps": {"classify": True},
        },
    )
    assert s.issue_number == 7
    assert s.issue_body == "boom"
    assert s.issue_author == "alice"
    assert s.existing_labels == ["triaged"]
    assert s.tone == "terse"


# -------------------- Classify --------------------


async def test_classify_sets_label_and_confidence() -> None:
    provider = _StubProvider(
        [_resp('{"classification":"bug","confidence":0.92,"rationale":"clear null deref"}')]
    )
    out = await classify_step.run(_state(), provider)
    assert out.classification == "bug"
    assert out.confidence == 0.92
    assert out.rationale == "clear null deref"
    assert out.status == "running"


async def test_classify_short_circuits_on_spam() -> None:
    provider = _StubProvider(
        [_resp('{"classification":"spam","confidence":0.99,"rationale":"ad for gambling site"}')]
    )
    out = await classify_step.run(_state(), provider)
    assert out.status == "complete"
    assert out.flag_reason == "classified as spam"


async def test_classify_short_circuits_on_low_confidence() -> None:
    provider = _StubProvider(
        [_resp('{"classification":"bug","confidence":0.2,"rationale":"unsure"}')]
    )
    out = await classify_step.run(_state(), provider)
    assert out.status == "complete"
    assert "below" in (out.flag_reason or "")


async def test_classify_handles_malformed_response() -> None:
    provider = _StubProvider([_resp("whoops not json")])
    out = await classify_step.run(_state(), provider)
    assert out.status == "complete"
    assert "malformed" in (out.flag_reason or "")


async def test_classify_rejects_unknown_label() -> None:
    provider = _StubProvider(
        [_resp('{"classification":"sparkly","confidence":0.9,"rationale":"nope"}')]
    )
    out = await classify_step.run(_state(), provider)
    assert out.status == "complete"


# -------------------- Comment --------------------


async def test_comment_builds_draft_and_labels() -> None:
    state = _state()
    state.classification = "bug"
    state.confidence = 0.9
    state.rationale = "stacktrace included"

    provider = _StubProvider([
        _resp(
            '{"comment":"Thanks for the report. Could you share the traceback?",'
            ' "proposed_labels":["bug","needs-info"],'
            ' "proposed_action":"comment_and_label"}'
        )
    ])
    out = await comment_step.run(state, provider)
    assert out.draft_comment is not None
    assert "traceback" in out.draft_comment
    assert out.proposed_labels == ["bug", "needs-info"]
    assert out.proposed_action == "comment_and_label"


async def test_comment_strips_unknown_labels() -> None:
    state = _state()
    state.classification = "bug"
    state.confidence = 0.9
    provider = _StubProvider([
        _resp(
            '{"comment":"ok","proposed_labels":["bug","invented-label"],'
            ' "proposed_action":"comment_and_label"}'
        )
    ])
    out = await comment_step.run(state, provider)
    assert out.proposed_labels == ["bug"]


async def test_comment_falls_back_on_malformed_response() -> None:
    state = _state()
    state.classification = "bug"
    state.confidence = 0.9
    provider = _StubProvider([_resp("nope")])
    out = await comment_step.run(state, provider)
    assert out.proposed_action == "flag_for_review"
    assert out.draft_comment is not None


async def test_comment_noop_without_classification() -> None:
    provider = _StubProvider([])  # should not be called
    out = await comment_step.run(_state(), provider)
    assert out.proposed_action == "flag_for_review"
    assert provider.last_messages is None


# -------------------- Orchestrator --------------------


async def test_orchestrator_classify_then_comment() -> None:
    from bugsift.agent import orchestrator

    provider = _StubProvider([
        _resp('{"classification":"bug","confidence":0.9,"rationale":"null deref"}'),
        _resp('{"comment":"ack","proposed_labels":["bug"],"proposed_action":"comment_and_label"}'),
    ])
    out = await orchestrator.run(_state(), provider)
    assert out.status == "complete"
    assert out.classification == "bug"
    assert out.draft_comment == "ack"
    assert out.proposed_action == "comment_and_label"
    assert len(out.llm_calls) == 2


async def test_orchestrator_short_circuit_on_spam_still_drafts_note() -> None:
    from bugsift.agent import orchestrator

    provider = _StubProvider([
        _resp('{"classification":"spam","confidence":0.99,"rationale":"ad"}')
    ])
    out = await orchestrator.run(_state(), provider)
    assert out.status == "complete"
    assert out.classification == "spam"
    assert out.draft_comment and "spam" in out.draft_comment.lower()
