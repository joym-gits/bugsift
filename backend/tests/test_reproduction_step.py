from __future__ import annotations

import pytest

from bugsift.agent.state import TriageState
from bugsift.agent.steps import reproduction as repro_step
from bugsift.llm.base import ChatMessage, LLMProvider, LLMResponse, Usage
from bugsift.repro import sandbox as sandbox_mod


class _StubLLM(LLMProvider):
    name = "stub"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.last: list[ChatMessage] | None = None

    async def complete(self, messages, *, max_tokens=1024, temperature=0.2, model=None):
        self.last = messages
        return self._response

    async def embed(self, text, *, model=None):
        raise NotImplementedError


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        usage=Usage(prompt_tokens=300, completion_tokens=80, cost_usd=0.0009),
    )


def _bug_state(body: str = "Traceback (most recent call last): AttributeError", language: str = "Python") -> TriageState:
    return TriageState(
        repo_id=1,
        repo_full_name="o/r",
        issue_number=7,
        issue_title="widget crashes on null",
        issue_body=body,
        classification="bug",
        confidence=0.9,
        repo_primary_language=language,
    )


def _sandbox_result(
    *,
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    error: str | None = None,
) -> sandbox_mod.SandboxResult:
    return sandbox_mod.SandboxResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=50,
        timed_out=timed_out,
        error=error,
    )


async def test_non_bug_classification_skips() -> None:
    state = _bug_state()
    state.classification = "question"
    out = await repro_step.run(state, _StubLLM(_resp("{}")))
    assert out.reproduction_verdict is None


async def test_no_signal_returns_insufficient_info() -> None:
    state = _bug_state(body="there is a problem")  # no version, error, or code
    out = await repro_step.run(state, _StubLLM(_resp("{}")))
    assert out.reproduction_verdict == "insufficient_info"


async def test_unsupported_language_is_flagged() -> None:
    state = _bug_state(language="Haskell")
    out = await repro_step.run(state, _StubLLM(_resp("{}")))
    assert out.reproduction_verdict == "unsupported_language"


async def test_disallowed_language_returns_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _bug_state(language="Python")
    out = await repro_step.run(
        state, _StubLLM(_resp("{}")), allowed_languages={"node"}
    )
    assert out.reproduction_verdict == "unsupported_language"


async def test_empty_script_returns_insufficient_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(*args, **kwargs):
        return _sandbox_result()

    monkeypatch.setattr(sandbox_mod, "run_script", fake_run)
    llm = _StubLLM(_resp('{"script": "", "expected_markers": [], "rationale": "nope"}'))
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "insufficient_info"


async def test_reproduced_when_marker_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(lang, script, **kwargs):
        return _sandbox_result(exit_code=1, stderr="AttributeError: x\n")

    monkeypatch.setattr(sandbox_mod, "run_script", fake_run)
    llm = _StubLLM(
        _resp(
            '{"script": "raise AttributeError(\\"x\\")",'
            ' "expected_markers": ["AttributeError"],'
            ' "rationale": "matches"}'
        )
    )
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "reproduced"
    assert "AttributeError" in (out.reproduction_log or "")


async def test_not_reproduced_when_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(*args, **kwargs):
        return _sandbox_result(exit_code=0, stdout="done\n")

    monkeypatch.setattr(sandbox_mod, "run_script", fake_run)
    llm = _StubLLM(
        _resp('{"script": "print(\\"done\\")", "expected_markers": ["AttributeError"], "rationale": "x"}')
    )
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "not_reproduced"


async def test_timeout_maps_to_sandbox_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(*args, **kwargs):
        return _sandbox_result(exit_code=None, timed_out=True, stderr="hang")

    monkeypatch.setattr(sandbox_mod, "run_script", fake_run)
    llm = _StubLLM(_resp('{"script": "pass", "expected_markers": [], "rationale": "x"}'))
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "sandbox_error"
    assert "timeout" in (out.reproduction_log or "").lower()


async def test_sandbox_unavailable_maps_to_sandbox_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(*args, **kwargs):
        raise sandbox_mod.SandboxUnavailable("daemon down")

    monkeypatch.setattr(sandbox_mod, "run_script", fake_run)
    llm = _StubLLM(_resp('{"script": "pass", "expected_markers": [], "rationale": "x"}'))
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "sandbox_error"
    assert "daemon down" in (out.reproduction_log or "")


async def test_malformed_builder_response_is_sandbox_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _StubLLM(_resp("not json"))
    out = await repro_step.run(_bug_state(), llm)
    assert out.reproduction_verdict == "sandbox_error"
    assert "malformed" in (out.reproduction_log or "").lower()
