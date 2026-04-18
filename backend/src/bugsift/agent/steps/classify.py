"""Step 2 — Classify.

One LLM call → one of ``{bug, feature-request, question, docs, spam, other}``
plus a confidence and one-sentence rationale. Short-circuits the pipeline if
the issue is spam, or if confidence is below :data:`MIN_CONFIDENCE`.
"""

from __future__ import annotations

import logging

from bugsift.agent.prompts import render
from bugsift.agent.state import LLMCallRecord, TriageState
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

STEP_NAME = "classify"
MIN_CONFIDENCE = 0.4
VALID_LABELS: set[str] = {"bug", "feature-request", "question", "docs", "spam", "other"}


async def run(state: TriageState, provider: LLMProvider) -> TriageState:
    prompt = render(
        "classify.j2",
        repo_full_name=state.repo_full_name,
        repo_primary_language=state.repo_primary_language,
        issue_title=state.issue_title,
        issue_body=state.issue_body,
        existing_labels=state.existing_labels,
    )
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=256,
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
        label = str(parsed["classification"]).strip().lower()
        if label not in VALID_LABELS:
            raise ValueError(f"unknown classification {label!r}")
        confidence = float(parsed["confidence"])
        rationale = str(parsed.get("rationale") or "").strip() or None
    except (KeyError, ValueError) as e:
        logger.warning(
            "classify: malformed response for %s#%s: %s",
            state.repo_full_name,
            state.issue_number,
            e,
        )
        return state.short_circuit("classifier returned malformed response")

    state.classification = label  # type: ignore[assignment]
    state.confidence = confidence
    state.rationale = rationale

    if label == "spam":
        return state.short_circuit("classified as spam")
    if confidence < MIN_CONFIDENCE:
        return state.short_circuit(f"confidence {confidence:.2f} below {MIN_CONFIDENCE}")
    return state
