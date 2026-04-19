"""Rule-based severity assignment for a finalized TriageState.

Severity is the single most actionable piece of metadata on a card —
it's what a maintainer sorts by when they open the queue with more
work than time. We compute it deterministically from signals already
on the state so two runs of the same pipeline always produce the same
severity, and so the logic stays transparent to operators.

Scale: ``blocker > high > medium > low``. Non-bug classifications
return ``None`` (severity doesn't apply to spam / off-topic).

Inputs we pay attention to:

- ``classification`` sets a base level.
  - ``bug`` → ``medium``
  - ``needs_info`` / ``question`` / ``feature-request`` → ``low``
  - anything else → ``None``

- Each "the bug is real and actionable" signal bumps severity up one
  level. Signals:
  - ``reproduction_verdict == "reproduced"`` (the sandbox actually
    triggered the failure — it's definitely a defect, not a
    misunderstanding)
  - at least one entry in ``regression_suspects`` (a recent push
    touched a suspected file — it's likely a regression, which is
    higher-priority than a latent bug)
  - feedback report count ≥ 5 (many users hit it — user impact)

- A maintainer can always override via the existing comment /
  labelling flow; this is only the automatic default.
"""

from __future__ import annotations

from bugsift.agent.state import TriageState

_LEVELS: tuple[str, ...] = ("low", "medium", "high", "blocker")

_MANY_USERS_THRESHOLD = 5


def compute_severity(
    state: TriageState, *, feedback_report_count: int = 0
) -> str | None:
    base = _base_for_classification(state.classification)
    if base is None:
        return None

    bumps = 0
    if state.reproduction_verdict == "reproduced":
        bumps += 1
    if state.regression_suspects:
        bumps += 1
    if feedback_report_count >= _MANY_USERS_THRESHOLD:
        bumps += 1

    return _bump(base, bumps)


def _base_for_classification(classification: str | None) -> str | None:
    if classification is None:
        return None
    c = classification.lower().strip()
    if c == "bug":
        return "medium"
    if c in ("needs_info", "needs-info", "question", "feature-request", "feature_request"):
        return "low"
    return None


def _bump(level: str, steps: int) -> str:
    if steps <= 0:
        return level
    try:
        idx = _LEVELS.index(level)
    except ValueError:
        return level
    idx = min(idx + steps, len(_LEVELS) - 1)
    return _LEVELS[idx]
