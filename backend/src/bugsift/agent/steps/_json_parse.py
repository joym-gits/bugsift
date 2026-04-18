"""Shared helper: coerce a model's response into a JSON dict.

Models sometimes wrap JSON in ``` fences or prose even when asked not to.
This helper strips the most common wrappers, then parses. Raises
:class:`ValueError` on failure with the snippet included for debugging.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    # Fall back: find first '{' and last '}' if there's surrounding prose.
    if not stripped.startswith("{"):
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first != -1 and last != -1 and last > first:
            stripped = stripped[first : last + 1]
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise ValueError(f"model returned non-JSON: {text[:200]!r}") from e
    if not isinstance(value, dict):
        raise ValueError(f"model returned non-object JSON: {text[:200]!r}")
    return value
