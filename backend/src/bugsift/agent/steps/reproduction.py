"""Step 5 — Reproduction.

Gates:
1. classification must be ``bug``.
2. issue body must include at least one signal — a version string, an error
   message, or a fenced code block.
3. repo primary language must be in the per-repo ``reproduce_languages``
   allow-list (Python / Node in v1).

If all gates pass, we ask the LLM to draft a minimal reproduction, run it in
the hardened sandbox, and tag the state with a verdict.

Verdicts (§6 Step 5):
- ``reproduced`` — sandbox output contains any ``expected_markers`` the
  builder supplied (so a non-zero exit *or* a printed error string counts).
- ``not_reproduced`` — script ran clean (exit 0 and no markers hit).
- ``insufficient_info`` — the builder itself refused, or no signal was
  present in the issue.
- ``unsupported_language`` — repo language isn't in the allow-list.
- ``sandbox_error`` — docker unavailable, timeout, malformed builder
  response, or any internal failure we couldn't classify further.
"""

from __future__ import annotations

import logging
import re

from bugsift.agent.prompts import render
from bugsift.agent.state import LLMCallRecord, TriageState
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider
from bugsift.repro import sandbox as sandbox_mod

logger = logging.getLogger(__name__)

STEP_NAME = "reproduction"

# Language alias map — repo config stores slugs that may not match the
# sandbox's native language names.
LANGUAGE_ALIASES: dict[str, sandbox_mod.Language] = {
    "python": "python",
    "py": "python",
    "node": "node",
    "nodejs": "node",
    "node.js": "node",
    "javascript": "node",
    "js": "node",
    "typescript": "node",
    "ts": "node",
}

_ERROR_TOKENS = re.compile(
    r"(Traceback|TypeError|ValueError|AttributeError|KeyError|ImportError|"
    r"ReferenceError|SyntaxError|Error:|Exception:|panic:|fatal error:|stack trace)",
    re.IGNORECASE,
)
_VERSION_TOKEN = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")


async def run(
    state: TriageState,
    provider: LLMProvider,
    *,
    allowed_languages: set[str] | None = None,
) -> TriageState:
    if state.classification != "bug":
        return state

    if not _has_signal(state.issue_body):
        state.reproduction_verdict = "insufficient_info"
        state.reproduction_log = (
            "no version, error message, or code snippet in the issue body"
        )
        return state

    language = _resolve_language(state.repo_primary_language, allowed_languages)
    if language is None:
        state.reproduction_verdict = "unsupported_language"
        state.reproduction_log = (
            f"primary language {state.repo_primary_language!r} is not in this "
            "repo's reproduce_languages allow-list"
        )
        return state

    prompt = render(
        "repro_script.j2",
        language=language,
        repo_full_name=state.repo_full_name,
        repo_primary_language=state.repo_primary_language,
        rationale=state.rationale,
        issue_title=state.issue_title,
        issue_body=state.issue_body,
    )
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=1200,
        temperature=0.0,
    )
    state.llm_calls.append(
        LLMCallRecord(
            step=STEP_NAME,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost_usd=response.usage.cost_usd,
        )
    )

    try:
        parsed = parse_json_object(response.content)
        script = str(parsed.get("script") or "").strip()
        markers = [str(m) for m in (parsed.get("expected_markers") or []) if str(m).strip()]
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(
            "reproduction: malformed builder response for %s#%s: %s",
            state.repo_full_name,
            state.issue_number,
            e,
        )
        state.reproduction_verdict = "sandbox_error"
        state.reproduction_log = "reproduction builder returned malformed JSON"
        return state

    if not script:
        state.reproduction_verdict = "insufficient_info"
        state.reproduction_log = "builder could not construct a minimal reproduction"
        return state

    try:
        result = await sandbox_mod.run_script(language, script)
    except sandbox_mod.SandboxUnavailable as e:
        state.reproduction_verdict = "sandbox_error"
        state.reproduction_log = f"sandbox unavailable: {e}"
        return state
    except Exception as e:  # pragma: no cover — unexpected
        logger.exception("reproduction: sandbox raised for %s#%s", state.repo_full_name, state.issue_number)
        state.reproduction_verdict = "sandbox_error"
        state.reproduction_log = f"sandbox error: {type(e).__name__}: {e}"
        return state

    if result.error is not None:
        state.reproduction_verdict = "sandbox_error"
        state.reproduction_log = result.truncated_log() or result.error
        return state
    if result.timed_out:
        state.reproduction_verdict = "sandbox_error"
        state.reproduction_log = f"timeout after {result.duration_ms} ms\n{result.truncated_log()}"
        return state

    state.reproduction_verdict = _verdict(result, markers)
    state.reproduction_log = result.truncated_log()
    return state


def _has_signal(body: str) -> bool:
    if not body:
        return False
    if _ERROR_TOKENS.search(body):
        return True
    if _CODE_FENCE.search(body):
        return True
    if _VERSION_TOKEN.search(body):
        return True
    return False


def _resolve_language(
    primary: str | None, allowed: set[str] | None
) -> sandbox_mod.Language | None:
    if not primary:
        return None
    language = LANGUAGE_ALIASES.get(primary.strip().lower())
    if language is None:
        return None
    if allowed is not None and language not in allowed and primary.lower() not in allowed:
        return None
    return language


def _verdict(result: sandbox_mod.SandboxResult, markers: list[str]) -> str:
    output = result.combined_output
    marker_hit = any(m and m in output for m in markers)
    if marker_hit:
        return "reproduced"
    if result.exit_code == 0:
        return "not_reproduced"
    # Non-zero exit with no marker hit — ambiguous. Call it not-reproduced
    # rather than lying about a reproduction.
    return "not_reproduced"
