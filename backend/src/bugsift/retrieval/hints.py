"""Extract file-path and identifier hints from an issue body.

Embedding similarity alone misses the strongest signal in most real-world
bug reports: the user pasted a stack trace. A single regex pass over the
body recovers those file paths (with line numbers) across the common
runtime stack-trace formats and feeds them to the retrieval step as
"known relevant" files, which we fetch directly from ``code_chunks``
and merge into the LLM's candidate list.

Kept deliberately regex-based, not language-aware — a false match on a
path-like string is cheap (we just end up with an extra candidate), but
a missed stack trace is expensive (retrieval falls back to embeddings
alone).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Conservative path charset: letters, digits, dots, dashes, underscores,
# slashes. Excludes whitespace, quotes, parens, colons so we can stop
# cleanly at the line-number separator.
_PATH = r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6}"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Python:  File "app/models.py", line 42, in save
    ("python", re.compile(rf'File "({_PATH})", line (\d+)')),
    # Node.js: at Foo.bar (/app/src/foo.js:42:15)   or   at /app/src/foo.js:42:15
    ("node", re.compile(rf"at [^(\n]*\(?({_PATH}):(\d+)(?::\d+)?\)?")),
    # Java:    at com.example.Foo.bar(Foo.java:42)
    ("java", re.compile(rf"at [\w$.]+\(({_PATH}):(\d+)\)")),
    # Go:      /app/handler.go:42 +0x123           or   handler.go:42
    ("go", re.compile(rf"\b({_PATH}\.go):(\d+)")),
    # Ruby:    from /app/lib/foo.rb:42:in `bar'
    ("ruby", re.compile(rf"from ({_PATH}):(\d+):in")),
    # PHP:     at /app/src/Foo.php:42              or  Foo.php on line 42
    ("php_path", re.compile(rf"({_PATH}\.php):(\d+)")),
    ("php_online", re.compile(rf"({_PATH}\.php)\s+on line\s+(\d+)", re.IGNORECASE)),
    # Generic: path/to/file.ext:LINE — catches Rust, C, Elixir, anything colon-separated.
    ("generic", re.compile(rf"\b({_PATH}):(\d+)\b")),
)

# An identifier mentioned in the issue: `functionName` or `ClassName.method`.
_IDENT = re.compile(r"`([A-Za-z_][\w.]*)`")


@dataclass(frozen=True)
class PathHint:
    path: str
    line: int
    source: str  # which regex produced it — useful in logs and tests


@dataclass(frozen=True)
class IssueHints:
    paths: tuple[PathHint, ...]
    identifiers: tuple[str, ...]

    @property
    def path_set(self) -> frozenset[str]:
        return frozenset(h.path for h in self.paths)


def extract_hints(text: str, *, max_paths: int = 20, max_identifiers: int = 20) -> IssueHints:
    """Pull file-path + identifier hints from ``text``.

    Ordered by source priority (Python traceback beats generic ``path:line``
    match) so the caller can use the first N without ranking. Deduplicated
    on (path, line)."""
    if not text:
        return IssueHints(paths=(), identifiers=())

    seen: set[tuple[str, int]] = set()
    paths: list[PathHint] = []
    for source, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            path = match.group(1)
            try:
                line = int(match.group(2))
            except (IndexError, ValueError):
                continue
            key = (path, line)
            if key in seen:
                continue
            seen.add(key)
            paths.append(PathHint(path=path, line=line, source=source))
            if len(paths) >= max_paths:
                break
        if len(paths) >= max_paths:
            break

    idents: list[str] = []
    seen_idents: set[str] = set()
    for match in _IDENT.finditer(text):
        token = match.group(1)
        if token in seen_idents or len(token) < 3:
            continue
        seen_idents.add(token)
        idents.append(token)
        if len(idents) >= max_identifiers:
            break

    return IssueHints(paths=tuple(paths), identifiers=tuple(idents))
