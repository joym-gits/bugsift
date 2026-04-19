"""TriageState flows through every orchestrator step.

Each step is a pure async function that returns a new or mutated state. A
step can short-circuit the pipeline by setting ``status="complete"`` with an
explanatory ``flag_reason``.

Only the fields relevant to the current phase are load-bearing; fields for
Phases 6–8 live here as typed placeholders so later steps can fill them in
without schema drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Classification = Literal["bug", "feature-request", "question", "docs", "spam", "other"]
Action = Literal["comment", "comment_and_close", "comment_and_label", "flag_for_review"]
Mode = Literal["dry-run", "auto"]


@dataclass
class DuplicateCandidate:
    issue_number: int
    rationale: str
    confidence: float


@dataclass
class SuspectedFile:
    file_path: str
    line_range: str
    rationale: str


@dataclass
class RegressionSuspectRecord:
    """Serializable shape of a regression suspect, stored on the card.

    Mirrors :class:`bugsift.regression.correlator.RegressionSuspect` but
    uses strings for the timestamp so the whole thing round-trips cleanly
    through the JSONB column.
    """

    commit_sha: str
    short_sha: str
    message_first_line: str
    author_name: str | None
    author_login: str | None
    pushed_at_iso: str
    pr_number: int | None
    ref: str | None
    overlapping_paths: list[str]


@dataclass
class LLMCallRecord:
    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class TriageState:
    # --- input (set by ingest step) ---
    repo_id: int
    repo_full_name: str
    issue_number: int
    issue_title: str
    issue_body: str
    issue_author: str = ""
    existing_labels: list[str] = field(default_factory=list)
    repo_primary_language: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    # --- repo config ---
    tone: str = "professional"
    label_map: dict[str, str] = field(default_factory=dict)
    auto_actions: dict[str, bool] = field(default_factory=dict)
    mode: Mode = "dry-run"
    enabled_steps: dict[str, bool] = field(default_factory=dict)
    monthly_budget_usd: float = 10.0

    # --- step outputs ---
    classification: Classification | None = None
    confidence: float | None = None
    rationale: str | None = None
    duplicates: list[DuplicateCandidate] = field(default_factory=list)
    suspected_files: list[SuspectedFile] = field(default_factory=list)
    regression_suspects: list[RegressionSuspectRecord] = field(default_factory=list)
    reproduction_verdict: str | None = None
    reproduction_log: str | None = None
    draft_comment: str | None = None
    proposed_labels: list[str] = field(default_factory=list)
    proposed_action: Action | None = None

    # --- flow control ---
    status: Literal["running", "complete"] = "running"
    flag_reason: str | None = None
    budget_limited: bool = False

    # --- accumulated usage ---
    llm_calls: list[LLMCallRecord] = field(default_factory=list)

    def short_circuit(self, reason: str) -> TriageState:
        self.status = "complete"
        self.flag_reason = reason
        return self

    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.llm_calls)
