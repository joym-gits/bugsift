#!/usr/bin/env python3
"""Run the classify step across the golden set and report accuracy.

Usage (from repo root):

    ANTHROPIC_API_KEY=sk-ant-... backend/.venv/bin/python scripts/eval-goldenset.py

Requires ``backend/tests/fixtures/goldenset.json`` (run seed-goldenset.py first)
and a real Anthropic key in the environment. The §16 acceptance gate: classify
accuracy must be \u226585% before moving past Phase 5.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from bugsift.agent.state import TriageState  # noqa: E402
from bugsift.agent.steps import classify as classify_step  # noqa: E402
from bugsift.llm.anthropic import AnthropicProvider  # noqa: E402

FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "goldenset.json"
TARGET_ACCURACY = 0.85


async def classify_one(provider: AnthropicProvider, fixture: dict) -> str | None:
    state = TriageState(
        repo_id=0,
        repo_full_name=fixture["repo"],
        repo_primary_language=None,
        issue_number=fixture["number"],
        issue_title=fixture["title"],
        issue_body=fixture["body"],
        existing_labels=[],  # intentionally empty — we want to test from-scratch classification
    )
    out = await classify_step.run(state, provider)
    return out.classification


async def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        return 2
    if not FIXTURES.exists():
        print(
            f"fixtures not found at {FIXTURES}; run seed-goldenset.py first.",
            file=sys.stderr,
        )
        return 2

    fixtures = json.loads(FIXTURES.read_text())
    provider = AnthropicProvider(key)

    correct = 0
    total = 0
    per_repo: dict[str, list[bool]] = defaultdict(list)
    confusion: Counter[tuple[str, str]] = Counter()
    misses: list[tuple[dict, str | None]] = []

    # Bounded concurrency so we don't hammer the rate limit.
    sem = asyncio.Semaphore(4)

    async def task(fixture: dict) -> tuple[dict, str | None]:
        async with sem:
            try:
                predicted = await classify_one(provider, fixture)
            except Exception as e:
                print(f"  ! classify failed for {fixture['repo']}#{fixture['number']}: {e}", file=sys.stderr)
                predicted = None
        return fixture, predicted

    results = await asyncio.gather(*(task(f) for f in fixtures))

    for fixture, predicted in results:
        expected = fixture["expected_classification"]
        total += 1
        hit = predicted == expected
        per_repo[fixture["repo"]].append(hit)
        confusion[(expected, predicted or "<fail>")] += 1
        if hit:
            correct += 1
        else:
            misses.append((fixture, predicted))

    accuracy = correct / total if total else 0.0

    print(f"\nClassification accuracy: {correct}/{total} = {accuracy:.2%}")
    print(f"Target: {TARGET_ACCURACY:.0%}")
    print()
    print("Per-repo:")
    for repo, results in per_repo.items():
        r = sum(results)
        print(f"  {repo}: {r}/{len(results)} = {r/len(results):.2%}")
    print()
    print("Confusion (expected -> predicted: count):")
    for (exp, pred), count in sorted(confusion.items(), key=lambda x: -x[1]):
        marker = "  " if exp == pred else "✗ "
        print(f"  {marker}{exp:20s} -> {pred:20s}: {count}")

    if misses:
        print("\nMisclassifications:")
        for fixture, predicted in misses:
            print(
                f"  {fixture['repo']}#{fixture['number']}: expected={fixture['expected_classification']}, "
                f"predicted={predicted}"
            )
            print(f"    title: {fixture['title'][:100]}")
            print(f"    url: {fixture['url']}")

    if accuracy >= TARGET_ACCURACY:
        print(f"\n✓ PASS — accuracy {accuracy:.2%} meets target {TARGET_ACCURACY:.0%}")
        return 0
    print(f"\n✗ FAIL — accuracy {accuracy:.2%} below target {TARGET_ACCURACY:.0%}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
