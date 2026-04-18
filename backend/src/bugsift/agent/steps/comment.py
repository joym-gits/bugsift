"""Step 6 — Comment draft.

One LLM call that, given everything the earlier steps produced, drafts the
triage comment, proposes labels from the repo's ``label_map``, and picks
one of the allowed actions.
"""

from __future__ import annotations

import logging

from bugsift.agent.prompts import render
from bugsift.agent.state import LLMCallRecord, TriageState
from bugsift.agent.steps._json_parse import parse_json_object
from bugsift.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

STEP_NAME = "comment"
VALID_ACTIONS: set[str] = {
    "comment",
    "comment_and_close",
    "comment_and_label",
    "flag_for_review",
}


async def run(state: TriageState, provider: LLMProvider) -> TriageState:
    if state.classification is None or state.confidence is None:
        # Without a classification there's nothing to summarise — flag instead.
        state.proposed_action = "flag_for_review"
        state.draft_comment = "Unable to classify this issue automatically; please review."
        return state

    prompt = render(
        "comment.j2",
        tone=state.tone,
        repo_full_name=state.repo_full_name,
        issue_number=state.issue_number,
        issue_title=state.issue_title,
        issue_body=state.issue_body,
        classification=state.classification,
        confidence=state.confidence,
        rationale=state.rationale or "",
        duplicates=state.duplicates,
        suspected_files=state.suspected_files,
        reproduction_verdict=state.reproduction_verdict,
        reproduction_log=state.reproduction_log or "",
        label_map=state.label_map or {},
    )
    response = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        max_tokens=1024,
        temperature=0.2,
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
        comment = str(parsed["comment"]).strip()
        raw_labels = parsed.get("proposed_labels") or []
        if not isinstance(raw_labels, list):
            raise ValueError("proposed_labels must be an array")
        valid_label_values = set(state.label_map.values())
        labels = [str(lbl) for lbl in raw_labels if str(lbl) in valid_label_values]
        action = str(parsed.get("proposed_action") or "flag_for_review").strip()
        if action not in VALID_ACTIONS:
            raise ValueError(f"unknown action {action!r}")
    except (KeyError, ValueError) as e:
        logger.warning(
            "comment: malformed response for %s#%s: %s",
            state.repo_full_name,
            state.issue_number,
            e,
        )
        state.draft_comment = (
            "Unable to draft a triage comment automatically; please review."
        )
        state.proposed_action = "flag_for_review"
        state.proposed_labels = []
        return state

    state.draft_comment = comment
    state.proposed_labels = labels
    state.proposed_action = action  # type: ignore[assignment]
    return state
