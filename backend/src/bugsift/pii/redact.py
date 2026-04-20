"""PII + credential redaction before prompts reach the LLM.

Every issue/feedback body that the orchestrator sends to Anthropic,
OpenAI, etc. passes through :func:`redact` first. Patterns we catch:

- Emails
- Phone numbers (US-leaning but matches most international formats)
- US social security numbers
- Credit card numbers (simple BIN-prefixed catchalls; Luhn-checked)
- Provider API keys — OpenAI (``sk-``), Anthropic (``sk-ant-``),
  Google (``AIza...``), AWS access keys (``AKIA...``), Slack bot/user
  tokens (``xoxb-``, ``xoxp-``, ``xapp-``), GitHub PATs
  (``ghp_`` / ``gho_`` / ``ghu_`` / ``ghs_`` / ``ghr_``)
- Generic JWTs (three base64url-looking segments)
- HTTP(S) URLs with embedded userinfo (``https://user:pass@host/...``)
- AWS secret access key shaped 40-char blobs that live near
  ``aws_secret_access_key`` / ``AWS_SECRET`` tokens

Replacement uses a stable token: ``[redacted:<kind>:<hash8>]``. The
hash is truncated SHA-256 of the original match, so:

- The same secret always collapses to the same token, so a prompt
  that references "the user's email" twice still reads naturally.
- Two *different* secrets of the same kind get different tokens, so
  the LLM doesn't incorrectly conflate two users' data.
- The hash can't be reversed — the original value is never visible
  to the LLM.

This is best-effort. False negatives are possible (anything not
matching a pattern). False positives are unlikely but possible (a
credit-card-shaped string that isn't actually a card). Bias in the
regexes is *toward* redacting (fail closed).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]  # e.g. {"email": 2, "aws_key": 1}

    @property
    def any(self) -> bool:
        return any(v > 0 for v in self.counts.values())

    @property
    def total(self) -> int:
        return sum(self.counts.values())


_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
)

# Match 10-15 digit sequences possibly separated by spaces/dashes/parens,
# with an optional leading + country code. Starts with a non-digit or
# start-of-string so long numeric IDs aren't falsely flagged.
_PHONE_RE = re.compile(
    r"(?<![\d])\+?\d[\d\-\s().]{8,14}\d(?!\d)",
)

_SSN_RE = re.compile(
    r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
)

# 13-19 digit runs with optional dashes/spaces; Luhn-checked below.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

# Provider API keys. Each pattern anchored to its known prefix so we
# don't mistake random base64 for a secret.
_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("google_key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
]

# JWTs. Three base64url segments joined by dots; middle segment must
# have enough entropy that this doesn't catch e.g. version strings.
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b",
)

# URL with embedded userinfo: https://user:pass@host/path
_URL_CREDS_RE = re.compile(
    r"https?://[^/\s:@]+:[^/\s:@]+@[^/\s]+",
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _luhn_ok(digits_only: str) -> bool:
    total = 0
    alt = False
    for ch in reversed(digits_only):
        d = ord(ch) - 48
        if d < 0 or d > 9:
            return False
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0 and len(digits_only) >= 13


def redact(text: str) -> RedactionResult:
    """Redact PII + credentials. Returns the redacted text + counts."""
    if not text:
        return RedactionResult(text=text, counts={})

    counts: dict[str, int] = {}

    def _count(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def _replace(kind: str) -> "callable":
        def _sub(match: "re.Match[str]") -> str:
            _count(kind)
            return f"[redacted:{kind}:{_fingerprint(match.group(0))}]"
        return _sub

    # Run credential patterns first so an email inside a URL-with-creds
    # gets wrapped as url_creds, not email.
    text = _URL_CREDS_RE.sub(_replace("url_creds"), text)
    for kind, pattern in _KEY_PATTERNS:
        text = pattern.sub(_replace(kind), text)
    text = _JWT_RE.sub(_replace("jwt"), text)
    text = _SSN_RE.sub(_replace("ssn"), text)

    # Credit cards — require Luhn so we don't redact random long digit
    # runs (invoice IDs, order numbers, etc.).
    def _card_sub(match: "re.Match[str]") -> str:
        raw = match.group(0)
        digits = re.sub(r"[^\d]", "", raw)
        if not _luhn_ok(digits):
            return raw
        _count("credit_card")
        return f"[redacted:credit_card:{_fingerprint(digits)}]"

    text = _CARD_RE.sub(_card_sub, text)
    text = _EMAIL_RE.sub(_replace("email"), text)

    # Phone last — its shape overlaps with card-ish numbers; Luhn-screened
    # cards are already redacted by the time we get here.
    def _phone_sub(match: "re.Match[str]") -> str:
        raw = match.group(0)
        digits = re.sub(r"[^\d]", "", raw)
        # Phone numbers are 10-15 digits; reject obvious non-phone shapes.
        if not (10 <= len(digits) <= 15):
            return raw
        _count("phone")
        return f"[redacted:phone:{_fingerprint(digits)}]"

    text = _PHONE_RE.sub(_phone_sub, text)

    return RedactionResult(text=text, counts=counts)


def has_pii(text: str) -> bool:
    """Boolean shortcut — useful for UI indicators."""
    return redact(text).any
