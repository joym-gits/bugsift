"""Render a GitHub-issue body from a feedback card.

The issue is read by a developer who's going to fix the bug. The
reporter is already gone (they submitted via the widget), so we do not
ask for more info and we don't embed a "suggested response" — anything
that looks like a question is noise. Instead the body carries three
things, in this order:

1. **What the user saw** — the verbatim report(s), with the URL and app
   version when we captured them. This is the ground truth.
2. **What bugsift found** — classification + rationale + the suspected
   files bugsift pulled from the code (retrieval) + the reproduction
   verdict and log tail. This is the work the maintainer doesn't have
   to redo.
3. **Admin notes** — optional, free-form text the approver added on
   their way out. Use it to nudge the developer toward a hypothesis the
   LLM didn't have context for.

The final ``Filed via bugsift`` line is how downstream automation
recognises issues we created.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

MAX_REPRO_LOG_CHARS = 2500
BUGSIFT_FOOTER_MARKER = "Filed via bugsift"


@dataclass(frozen=True)
class ReportSnippet:
    body_text: str
    url: str | None
    app_version: str | None
    created_at_iso: str


@dataclass(frozen=True)
class SuspectedFileSnippet:
    file_path: str
    line_range: str
    rationale: str


def build_issue(
    *,
    reports: list[ReportSnippet],
    rationale: str | None,
    classification: str | None,
    confidence: float | None,
    suspected_files: Iterable[SuspectedFileSnippet],
    reproduction_verdict: str | None,
    reproduction_log: str | None,
    admin_note: str | None = None,
) -> tuple[str, str]:
    """Return ``(title, body)`` for the new GitHub issue.

    Title is the first line of the first report (clipped). Body is the
    structured markdown block described in the module docstring.
    """
    title = _make_title(reports)
    sections: list[str] = []

    sections.append(_render_user_reports(reports))

    findings: list[str] = []
    if classification:
        conf = f" · confidence {confidence:.2f}" if confidence is not None else ""
        findings.append(f"**Classification**: `{classification}`{conf}")
    if rationale:
        findings.append(rationale.strip())

    files = list(suspected_files)
    if files:
        findings.append(
            "**Suspected files** (pulled from the indexed repo):\n"
            + "\n".join(
                f"- `{f.file_path}:{f.line_range}` — {f.rationale}" for f in files
            )
        )

    if reproduction_verdict:
        repro_bits = [f"**Reproduction verdict**: `{reproduction_verdict}`"]
        if reproduction_log:
            log = reproduction_log.strip()
            if len(log) > MAX_REPRO_LOG_CHARS:
                log = log[-MAX_REPRO_LOG_CHARS:]
            repro_bits.append("```\n" + log + "\n```")
        findings.append("\n\n".join(repro_bits))

    if findings:
        sections.append("## What bugsift found\n\n" + "\n\n".join(findings))

    if admin_note and admin_note.strip():
        sections.append(
            "## Admin notes\n\n"
            + "> " + admin_note.strip().replace("\n", "\n> ")
        )

    sections.append(
        f"---\n_{BUGSIFT_FOOTER_MARKER} from {len(reports)} user report"
        f"{'s' if len(reports) != 1 else ''}._"
    )
    return title, "\n\n".join(sections)


def _make_title(reports: list[ReportSnippet]) -> str:
    if not reports:
        return "User feedback"
    # First non-empty line of the first report's body, clipped to ~90 chars.
    body = reports[0].body_text
    for raw in body.splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        if len(line) <= 90:
            return line
        # Cut on a word boundary.
        clipped = line[:90]
        space = clipped.rfind(" ")
        if space > 40:
            clipped = clipped[:space]
        return clipped.rstrip(",. ") + "\u2026"
    return "User feedback"


def _render_user_reports(reports: list[ReportSnippet]) -> str:
    if not reports:
        return "## What the user saw\n\n_(no reports attached)_"
    lines: list[str] = ["## What the user saw"]
    for idx, r in enumerate(reports, start=1):
        header_bits: list[str] = []
        if len(reports) > 1:
            header_bits.append(f"**Report {idx}**")
        if r.url:
            header_bits.append(f"url: `{r.url}`")
        if r.app_version:
            header_bits.append(f"app version: `{r.app_version}`")
        header_bits.append(f"reported {r.created_at_iso}")
        lines.append(" · ".join(header_bits))
        quoted = "> " + (r.body_text.strip().replace("\n", "\n> ") or "_(empty)_")
        lines.append(quoted)
    return "\n\n".join(lines)


def snippets_from_suspected_json(value: Any) -> list[SuspectedFileSnippet]:
    """Accept the heterogeneous shapes we persist on ``TriageCard`` and
    normalise them to the snippet dataclass. Unknown shapes are dropped."""
    if not isinstance(value, list):
        return []
    out: list[SuspectedFileSnippet] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append(
            SuspectedFileSnippet(
                file_path=str(item.get("file_path", "")).strip(),
                line_range=str(item.get("line_range", "")).strip(),
                rationale=str(item.get("rationale", "")).strip(),
            )
        )
    return [s for s in out if s.file_path]
