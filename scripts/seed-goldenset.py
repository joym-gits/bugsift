#!/usr/bin/env python3
"""Scrape 30 real issues from 3 OSS repos and write them as labelled fixtures.

Run from the repo root with the backend venv:

    backend/.venv/bin/python scripts/seed-goldenset.py

Writes ``backend/tests/fixtures/goldenset.json``. Existing file is overwritten;
review the auto-applied ``expected_classification`` field and correct it by
hand before trusting the eval numbers.

We deliberately pull *closed* issues — they're easier to pre-label from their
final state (labels applied, closed-as-dup, etc.) — but the classification
target is what you'd want the pipeline to say *when the issue first opened*.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

REPOS = [
    "pallets/flask",
    "expressjs/express",
    "psf/requests",
]
PER_REPO = 10

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "backend" / "tests" / "fixtures" / "goldenset.json"

GH_API = "https://api.github.com"


def heuristic_classification(labels: list[str], title: str, body: str) -> str:
    """Best-effort pre-label from the issue's existing GitHub labels.

    Human must still review — this is a starting point, not ground truth.
    """
    name_set = {lbl.lower() for lbl in labels}
    if any("spam" in l or "advertising" in l for l in name_set):
        return "spam"
    if any(l in name_set for l in ("bug", "type: bug", "kind/bug")):
        return "bug"
    if any(
        l in name_set
        for l in ("enhancement", "feature", "feature-request", "kind/feature", "type: feature")
    ):
        return "feature-request"
    if any(l in name_set for l in ("question", "support", "usage")):
        return "question"
    if any(l in name_set for l in ("docs", "documentation")):
        return "docs"
    # Heuristic over title if no label fits.
    title_lower = title.lower()
    if title_lower.startswith(("how to", "how do i", "question")):
        return "question"
    if any(kw in title_lower for kw in ("docs", "documentation", "typo")):
        return "docs"
    if any(kw in title_lower for kw in ("add ", "support ", "request ", "feature:")):
        return "feature-request"
    if any(kw in title_lower for kw in ("crash", "error", "broken", "fails", "regression")):
        return "bug"
    return "other"


def _is_usable_issue(item: dict) -> bool:
    if item.get("pull_request"):
        return False
    title = (item.get("title") or "").strip().lower()
    body = (item.get("body") or "").strip()
    if not title or not body or len(body) < 80:
        return False
    if title in ("<spam>", "[deleted]") or "redacted" in title:
        return False
    if title.startswith(("missing tests:", "security:", "ci:")) and (item.get("user") or {}).get("type") == "Bot":
        return False
    return True


def fetch_issues(client: httpx.Client, repo: str, n: int) -> list[dict]:
    """Pull recent closed issues, filter bot/redacted junk, dedupe by title."""
    url = f"{GH_API}/repos/{repo}/issues"
    params: dict[str, str | int] = {
        "state": "closed",
        "per_page": 100,
        "sort": "created",
        "direction": "desc",
    }
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    seen_titles: set[str] = set()
    out: list[dict] = []
    page = 1
    while len(out) < n and page <= 10:
        params["page"] = page
        response = client.get(url, params=params, headers=headers, timeout=20.0)
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        for item in batch:
            if not _is_usable_issue(item):
                continue
            norm = (item.get("title") or "").strip().lower()
            if norm in seen_titles:
                continue
            seen_titles.add(norm)
            labels = [lbl.get("name", "") for lbl in (item.get("labels") or [])]
            out.append(
                {
                    "repo": repo,
                    "number": item["number"],
                    "title": item["title"],
                    "body": item.get("body") or "",
                    "labels": labels,
                    "url": item["html_url"],
                    "expected_classification": heuristic_classification(
                        labels, item["title"], item.get("body") or ""
                    ),
                    "expected_duplicate_of": None,
                }
            )
            if len(out) >= n:
                break
        page += 1
    return out


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fixtures: list[dict] = []
    with httpx.Client() as client:
        for repo in REPOS:
            print(f"fetching {PER_REPO} issues from {repo}…", file=sys.stderr)
            fixtures.extend(fetch_issues(client, repo, PER_REPO))
    OUTPUT.write_text(json.dumps(fixtures, indent=2))
    print(
        f"wrote {len(fixtures)} fixtures to {OUTPUT.relative_to(ROOT)}",
        file=sys.stderr,
    )
    print(
        "Review the `expected_classification` field on each entry before trusting eval.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
