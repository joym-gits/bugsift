"""Parse and match GitHub-style CODEOWNERS files.

GitHub's CODEOWNERS syntax (and the GitLab / Gitea variants) is a
gitignore-shaped list of rules. Each non-empty non-comment line is

    <pattern>    <owner1> <owner2> ...

Pattern semantics we support (enough for real repos — pathological
edge cases are less valuable than predictable behaviour):

- ``*`` matches within a single path segment.
- ``**`` matches any number of path segments (including zero).
- Leading ``/`` anchors at repo root; otherwise the pattern matches at
  any depth.
- Trailing ``/`` means directory-only (we treat it as matching that
  directory and anything inside).
- Last matching rule wins — that's what GitHub does.

Owners we surface:

- ``@username`` — added to the output list with the ``@`` stripped so
  the GitHub assignees API accepts it.
- ``@org/team`` — **skipped** with a log line; the assignees API
  doesn't accept team slugs and requested_reviewers on an issue is a
  separate flow we're not building yet.
- Bare email addresses — skipped for the same reason (no good issue
  assignee mapping).

Return order is "most-specific rule's owners first, deduped preserving
order". A file without a matching rule returns ``[]``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeownersRule:
    pattern: str
    owners: list[str]
    raw_line: str


def parse(text: str) -> list[CodeownersRule]:
    """Split a CODEOWNERS file into rules in the order they appear."""
    rules: list[CodeownersRule] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        pattern = tokens[0]
        owners = [o for o in tokens[1:] if o]
        rules.append(CodeownersRule(pattern=pattern, owners=owners, raw_line=raw_line))
    return rules


def owners_for_file(rules: list[CodeownersRule], file_path: str) -> list[str]:
    """Return the user logins (``@username`` → ``username``) from the
    last rule in ``rules`` that matches ``file_path``.

    Teams and bare emails are dropped — see module docstring."""
    # GitHub semantics: *last* match wins. Walk in reverse and stop on
    # the first hit.
    for rule in reversed(rules):
        if _matches(rule.pattern, file_path):
            return _filter_to_users(rule.owners)
    return []


def owners_for_files(
    rules: list[CodeownersRule], file_paths: list[str]
) -> list[str]:
    """Dedupe + preserve order across all matching rules.

    Used when a card has several suspected files — we return the union
    of per-file owners so the maintainer sees everyone who could have
    caused this on one card."""
    out: list[str] = []
    seen: set[str] = set()
    for path in file_paths:
        for user in owners_for_file(rules, path):
            if user in seen:
                continue
            seen.add(user)
            out.append(user)
    return out


def _filter_to_users(owners: list[str]) -> list[str]:
    out: list[str] = []
    for owner in owners:
        if owner.startswith("@") and "/" not in owner:
            out.append(owner[1:])
        elif owner.startswith("@") and "/" in owner:
            # @org/team — skip, can't assign via the issue API.
            logger.debug("codeowners: skipping team %s", owner)
        # else: bare email or malformed — skip silently
    return out


def _matches(pattern: str, file_path: str) -> bool:
    """Match a CODEOWNERS pattern against a repo-relative path.

    Implementation is a glob → regex translator that honours the
    subset described in the module docstring. We normalise both sides
    to no leading slash so patterns like ``/app/**`` and paths like
    ``app/foo.py`` line up.
    """
    normalised = file_path.lstrip("/")

    # Drop a trailing slash on the pattern — we treat it as directory-
    # matching, which is the same as matching the dir and its contents.
    anchored = pattern.startswith("/")
    is_dir_only = pattern.endswith("/")
    core = pattern.strip("/")

    regex = _glob_to_regex(core, directory_only=is_dir_only)
    if anchored:
        full_re = f"^{regex}$"
    else:
        # Un-anchored: match at any depth.
        full_re = f"(?:^|/){regex}$"
    return re.search(full_re, normalised) is not None


def _glob_to_regex(glob: str, *, directory_only: bool) -> str:
    """Translate a CODEOWNERS glob into a Python regex.

    - ``**`` → any number of path segments (``(?:.*)``)
    - ``*``  → any chars except ``/`` (``[^/]*``)
    - ``?``  → single char except ``/`` (``[^/]``)
    - anything else is escaped
    """
    parts: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if i + 1 < len(glob) and glob[i + 1] == "*":
                parts.append(".*")
                i += 2
                # Collapse a trailing ``/`` after ``**`` so the regex
                # doesn't require a literal slash.
                if i < len(glob) and glob[i] == "/":
                    i += 1
            else:
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c in ".^$+{}[]|()\\":
            parts.append(re.escape(c))
            i += 1
        else:
            parts.append(c)
            i += 1
    body = "".join(parts)
    if directory_only:
        # A "dir/" pattern matches both the dir itself and anything inside.
        body = f"{body}(?:/.*)?"
    return body
